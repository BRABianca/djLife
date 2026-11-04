"""Fluxo de organizacao auditavel pela interface web (modo ADM/Owner).

Encadeia varredura, classificacao, plano (dry-run), auditoria item a item,
aplicacao com journal e reversao. Somente `apply` e `undo` escrevem no
filesystem; ambos exigem o token de administracao e sao registrados no journal
para permitir desfazer. A varredura reaproveita `setup.ScanJob`; as tarefas
longas usam `jobs.TaskJob`.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from djlife import apply as apply_mod
from djlife import classifier, db, planner, taxonomy
from djlife.config import FILE_STRATEGIES, Config
from djlife.ui.jobs import TaskJob


class OrganizeError(RuntimeError):
    """Falha no fluxo de organizacao (configuracao ausente ou catalogo inacessivel)."""


def _open(cfg: Config) -> sqlite3.Connection:
    path = cfg.db_path
    if not path.exists():
        raise OrganizeError(f"catalogo inexistente: {path}")
    return db.open_catalog(path)


def _target(cfg: Config) -> Path:
    if cfg.files.target is None:
        raise OrganizeError("defina files.target no djlife.toml antes de organizar")
    return Path(cfg.files.target)


def status(cfg: Config) -> dict[str, Any]:
    """Configuracao corrente que orienta a organizacao (somente leitura)."""
    roots = [str(root) for root in cfg.library.roots]
    return {
        "configured": bool(roots),
        "roots": roots,
        "target": str(cfg.files.target) if cfg.files.target else None,
        "strategy": cfg.files.strategy,
        "strategies": list(FILE_STRATEGIES),
        "template": cfg.files.template,
        "unknown_dir": cfg.files.unknown_dir,
        "catalog": str(cfg.db_path),
        "catalog_exists": cfg.db_path.exists(),
    }


def _build_plan(cfg: Config, conn: sqlite3.Connection) -> planner.Plan:
    return planner.build_plan(
        conn,
        target=_target(cfg),
        template=cfg.files.template,
        unknown_dir=cfg.files.unknown_dir,
        strategy=cfg.files.strategy,
    )


def plan_payload(cfg: Config) -> dict[str, Any]:
    """Plano de organizacao (dry-run) com itens auditaveis e resumo por genero."""
    conn = _open(cfg)
    try:
        built = _build_plan(cfg, conn)
    finally:
        conn.close()

    items = [
        {
            "track_id": item.track_id,
            "file_id": item.file_id,
            "src": str(item.src),
            "dst": str(item.dst) if item.dst else None,
            "genre": item.genre,
            "subgenre": item.subgenre,
            "status": item.status,
        }
        for item in built.items
    ]
    return {
        "target": str(built.target),
        "strategy": built.strategy,
        "summary": {
            "total": len(built.items),
            "ready": built.count(planner.STATUS_READY),
            "exists": built.count(planner.STATUS_EXISTS),
            "conflict": built.count(planner.STATUS_CONFLICT),
            "unclassified": built.count(planner.STATUS_UNCLASSIFIED),
        },
        "by_genre": [{"genre": name, "total": total} for name, total in built.by_genre],
        "items": items,
    }


def start_classify(cfg: Config) -> TaskJob:
    """Resolve genero em camadas (tags e regras) em thread, gravando track_genres."""
    if not cfg.db_path.exists():
        raise OrganizeError(f"catalogo inexistente: {cfg.db_path}")
    job = TaskJob(task="classify")

    def worker() -> None:
        try:
            conn = db.open_catalog(cfg.db_path)
            try:
                taxonomy_path = cfg.classification.taxonomy
                if not Path(taxonomy_path).exists():
                    taxonomy_path = str(taxonomy.default_taxonomy_path())
                tree = taxonomy.load_taxonomy(taxonomy_path)
                rules = classifier.load_rules(cfg.classification.local_taxonomy)
                genres = taxonomy.sync(conn, tree)
                layers = tuple(
                    layer for layer in cfg.classification.enable if layer in classifier.LAYERS
                )
                result = classifier.classify(conn, tree, rules, layers)
            finally:
                conn.close()
            job.result = {
                "taxonomy_version": tree.version,
                "genres": genres,
                "layers": list(layers),
                "rules": len(rules),
                "tracks": result.tracks,
                "tagged": result.tagged,
                "ruled": result.ruled,
                "unresolved": result.unresolved,
                "inserted": result.inserted,
            }
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.message = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_apply(
    cfg: Config,
    *,
    track_ids: list[int] | None = None,
    write_tags: bool = True,
) -> TaskJob:
    """Executa o plano (hardlink/move + tags DJLIFE_* + journal) em thread.

    `track_ids` restringe a aplicacao a itens auditados; `None` aplica todos os
    prontos. Apenas itens com status `ready` sao considerados.
    """
    _target(cfg)  # valida a configuracao antes de disparar a thread
    if not cfg.db_path.exists():
        raise OrganizeError(f"catalogo inexistente: {cfg.db_path}")
    selected = set(track_ids) if track_ids is not None else None
    job = TaskJob(task="apply")

    def worker() -> None:
        try:
            conn = db.open_catalog(cfg.db_path)
            try:
                built = _build_plan(cfg, conn)
                items = tuple(
                    item
                    for item in built.items
                    if item.status == planner.STATUS_READY
                    and (selected is None or item.track_id in selected)
                )
                plan = planner.Plan(target=built.target, strategy=built.strategy, items=items)
                result = apply_mod.apply(conn, plan, write_tags=write_tags)
            finally:
                conn.close()
            job.result = {
                "batch": result.batch,
                "strategy": result.strategy,
                "linked": result.linked,
                "moved": result.moved,
                "tagged": result.tagged,
                "skipped": result.skipped,
                "errors": result.errors,
                "applied": result.applied,
                "requested": len(items),
            }
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.message = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_undo(cfg: Config, *, batch: str | None = None) -> TaskJob:
    """Reverte um lote do journal (padrao: o ultimo) em thread."""
    if not cfg.db_path.exists():
        raise OrganizeError(f"catalogo inexistente: {cfg.db_path}")
    job = TaskJob(task="undo")

    def worker() -> None:
        try:
            conn = db.open_catalog(cfg.db_path)
            try:
                result = apply_mod.undo(
                    conn,
                    batch,
                    stop=cfg.files.target,
                    quarantine_dir=cfg.files.quarantine_dir,
                )
            finally:
                conn.close()
            job.result = {
                "batch": result.batch,
                "removed": result.removed,
                "restored": result.restored,
                "untagged": result.untagged,
                "errors": result.errors,
            }
            if result.batch is None:
                job.message = "nada a reverter"
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.message = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job


def history(cfg: Config, limit: int = 20) -> dict[str, Any]:
    """Lotes registrados no journal, com contagem de operacoes e pendentes."""
    conn = _open(cfg)
    try:
        rows = list(
            conn.execute(
                "SELECT batch,"
                " MIN(created_at) AS created_at,"
                " COUNT(*) AS ops,"
                " SUM(CASE WHEN undone = 0 THEN 1 ELSE 0 END) AS pending,"
                " SUM(CASE WHEN op IN ('hardlink', 'move') THEN 1 ELSE 0 END) AS files,"
                " SUM(CASE WHEN op = 'tag' THEN 1 ELSE 0 END) AS tags,"
                " MIN(strategy) AS strategy"
                " FROM journal GROUP BY batch ORDER BY MAX(id) DESC LIMIT ?",
                (limit,),
            )
        )
    finally:
        conn.close()
    batches = [
        {
            "batch": str(row["batch"]),
            "created_at": str(row["created_at"]),
            "strategy": str(row["strategy"]),
            "ops": int(row["ops"]),
            "files": int(row["files"]),
            "tags": int(row["tags"]),
            "pending": int(row["pending"]),
        }
        for row in rows
    ]
    return {"batches": batches, "total": len(batches)}
