"""Consultas de leitura para a interface web local.

Todas as funcoes abrem conexoes efemeras no catalogo SQLite e devolvem
estruturas prontas para serializacao JSON, mantendo a CLI e a UI desacopladas.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from djlife import db, report
from djlife.config import Config
from djlife.integrations import base as integrations_base

PIPELINE: tuple[dict[str, str], ...] = (
    {
        "layer": "L0",
        "name": "Tags",
        "status": "ativo",
        "detail": "Leitura direta de TCON / (c)gen / Genre gravadas no arquivo.",
    },
    {
        "layer": "L1",
        "name": "Regras",
        "status": "ativo",
        "detail": "Padroes regex locais (genres.local.yaml) sobre titulo, artista,"
        " album e caminho.",
    },
    {
        "layer": "L2",
        "name": "DSP + classificador",
        "status": "parcial",
        "detail": "BPM e tonalidade (Camelot/Open Key) extraidos de audio com librosa"
        " (Essentia como backend opcional); o classificador supervisionado vem depois.",
    },
    {
        "layer": "L3",
        "name": "Embeddings CLAP",
        "status": "parcial",
        "detail": "Vetores de audio (CLAP) gravados em embeddings e k-NN que propoe genero"
        " para faixas sem rotulo (source=embedding).",
    },
    {
        "layer": "L4",
        "name": "Foundation models",
        "status": "parcial",
        "detail": "MERT (extra `ml`) e MuQ (extra `muq`) como embedders alternativos do L3,"
        " refinando genero/subgenero por similaridade acustica.",
    },
)

COMMANDS: tuple[dict[str, str], ...] = (
    {
        "name": "scan",
        "usage": "djlife scan [RAIZES...]",
        "summary": "Varre as raizes, atualiza o catalogo e indexa metadados.",
        "detail": "Deteccao incremental por mtime/size; erros vao para scan_errors "
        "sem interromper a varredura.",
    },
    {
        "name": "classify",
        "usage": "djlife classify",
        "summary": "Resolve genero em camadas (tags e regras) e grava track_genres.",
        "detail": "Cada decisao guarda a camada de origem e a confianca (A/B/C).",
    },
    {
        "name": "stats",
        "usage": "djlife stats",
        "summary": "Mostra estatisticas do catalogo e cobertura de tags.",
        "detail": "Arquivos, faixas, duracao total, distribuicao por extensao e lacunas"
        " de metadados.",
    },
    {
        "name": "search",
        "usage": "djlife search TERMO [--limit N]",
        "summary": "Busca faixas por titulo, artista, album ou caminho.",
        "detail": "Consulta textual direta no catalogo SQLite.",
    },
    {
        "name": "plan",
        "usage": "djlife plan [--target DIR] [--strategy hardlink|move|tag_only]",
        "summary": "Mostra o plano de organizacao (dry-run), sem tocar no filesystem.",
        "detail": "Agrupa por genero e marca conflitos, itens prontos e nao classificados.",
    },
    {
        "name": "apply",
        "usage": "djlife apply --yes [--no-tags]",
        "summary": "Executa o plano: hardlink/move, tags DJLIFE_* e journal.",
        "detail": "Toda escrita e registrada no journal para permitir reverter.",
    },
    {
        "name": "undo",
        "usage": "djlife undo [--batch LOTE]",
        "summary": "Reverte um apply usando o journal.",
        "detail": "Remove links criados e restaura originais movidos.",
    },
    {
        "name": "duplicates",
        "usage": "djlife duplicates [--fingerprint]",
        "summary": "Detecta duplicatas em 3 niveis: hash -> fingerprint -> ISRC/MBID.",
        "detail": "Fingerprint usa Chromaprint (extra opcional).",
    },
    {
        "name": "versions",
        "usage": "djlife versions",
        "summary": "Classifica versoes (Original/Extended/Radio/Remix/Bootleg) por regras.",
        "detail": "Grava o resultado em file_versions com confianca.",
    },
    {
        "name": "analyze",
        "usage": "djlife analyze [--apply] [--fast] [--backend NOME]",
        "summary": "Extrai BPM e tonalidade (Camelot/Open Key) dos arquivos.",
        "detail": "Backend librosa roda nativo no Windows; Essentia fica como extra opcional."
        " Falhas de decodificacao vao para scan_errors.",
    },
    {
        "name": "embed",
        "usage": "djlife embed [--apply] [--force] [--limit N] [--model ID]",
        "summary": "Calcula embeddings de audio (CLAP) e grava em embeddings.",
        "detail": "Dry-run por padrao; o modelo roda em CPU e so e carregado com --apply"
        " (extra opcional `ml`).",
    },
    {
        "name": "neighbors",
        "usage": "djlife neighbors [--apply] [--k N] [--min-similarity F]",
        "summary": "Propoe genero por k-NN sobre embeddings para faixas sem rotulo.",
        "detail": "Grava em track_genres com source=embedding, sem sobrescrever tags/regras"
        " e com confianca pela concordancia da vizinhanca.",
    },
    {
        "name": "dedupe",
        "usage": "djlife dedupe [--apply --yes] [--quarantine DIR]",
        "summary": "Planeja a quarentena de duplicatas, movendo sem deletar.",
        "detail": "Politica marcar-nao-deletar: redundantes vao para a quarentena, reversivel.",
    },
    {
        "name": "status",
        "usage": "djlife status [--software rekordbox|serato]",
        "summary": "Verifica a integridade dos bancos DJ (itens que resolvem para arquivos).",
        "detail": "Mostra itens totais, resolvidos e ausentes por software.",
    },
    {
        "name": "relink",
        "usage": "djlife relink [--software NOME] [--apply --yes]",
        "summary": "Aponta os bancos DJ para os destinos atuais do catalogo.",
        "detail": "Dry-run por padrao; com --apply cria backup verificado antes de gravar.",
    },
    {
        "name": "ui",
        "usage": "djlife ui [--port 8765] [--no-open]",
        "summary": "Sobe esta interface web local para explorar o catalogo.",
        "detail": "Servidor HTTP da stdlib lendo o catalogo em modo somente leitura.",
    },
)

SAFETY: tuple[dict[str, str], ...] = (
    {
        "title": "Catalogo como fonte de verdade",
        "detail": "O SQLite e a unica fonte oficial; o filesystem e uma projecao reorganizavel.",
    },
    {
        "title": "Dry-run obrigatorio",
        "detail": "Nenhuma escrita no filesystem acontece sem um plano revisado e confirmado.",
    },
    {
        "title": "Marcar, nao deletar",
        "detail": "Duplicatas sao movidas para quarentena e podem ser revertidas pelo journal.",
    },
    {
        "title": "Backup verificado",
        "detail": "Relink em bancos de terceiros exige backup com tamanho conferido"
        " antes de gravar.",
    },
    {
        "title": "Offline-first",
        "detail": "DSP e regras rodam localmente; a interface nao envia dados para fora.",
    },
)


class CatalogUnavailable(RuntimeError):
    """Catalogo SQLite ausente ou inacessivel."""


def _connect(cfg: Config) -> sqlite3.Connection:
    path = cfg.db_path
    if not path.exists():
        raise CatalogUnavailable(f"catalogo inexistente: {path}")
    return db.connect(path, create=False)


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def _meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


_GENRE_DIST = """
    SELECT g.name AS name, g.slug AS slug, COUNT(DISTINCT tg.track_id) AS total
    FROM track_genres tg
    JOIN genres g ON g.id = tg.genre_id
    GROUP BY g.id
    ORDER BY total DESC, g.name
    LIMIT 40
"""


def overview(cfg: Config) -> dict[str, Any]:
    """Resumo consolidado do catalogo para o painel principal."""
    conn = _connect(cfg)
    try:
        stats = report.collect_stats(conn)
        genres_active = _scalar(conn, "SELECT COUNT(*) FROM genres WHERE is_active = 1")
        classified = _scalar(conn, "SELECT COUNT(DISTINCT track_id) FROM track_genres")
        fingerprints = _scalar(conn, "SELECT COUNT(*) FROM fingerprints")
        analyzed = _scalar(conn, "SELECT COUNT(DISTINCT file_id) FROM audio_analysis")
        backends = [
            {
                "analyzer": str(row["analyzer"]),
                "version": str(row["analysis_version"]),
                "total": int(row["total"]),
            }
            for row in conn.execute(
                "SELECT analyzer, analysis_version, COUNT(*) AS total FROM audio_analysis"
                " GROUP BY analyzer, analysis_version ORDER BY analyzer, analysis_version"
            )
        ]
        embedded = _scalar(conn, "SELECT COUNT(DISTINCT file_id) FROM embeddings")
        models = [
            {
                "model": str(row["model"]),
                "version": str(row["model_version"]),
                "dim": int(row["dim"]),
                "total": int(row["total"]),
            }
            for row in conn.execute(
                "SELECT model, model_version, dim, COUNT(*) AS total FROM embeddings"
                " GROUP BY model, model_version, dim ORDER BY model, model_version"
            )
        ]
        proposed = _scalar(conn, "SELECT COUNT(*) FROM track_genres WHERE source = 'embedding'")
        batches = _scalar(conn, "SELECT COUNT(DISTINCT batch) FROM journal")
        dup_groups = [
            {"kind": str(row["kind"]), "total": int(row["total"])}
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS total FROM dup_groups GROUP BY kind ORDER BY kind"
            )
        ]
        versions = [
            {"version": str(row["version"]), "total": int(row["total"])}
            for row in conn.execute(
                "SELECT version, COUNT(*) AS total FROM file_versions"
                " GROUP BY version ORDER BY total DESC, version"
            )
        ]
        genre_distribution = [
            {"name": str(row["name"]), "slug": str(row["slug"]), "total": int(row["total"])}
            for row in conn.execute(_GENRE_DIST)
        ]
        taxonomy_version = _meta(conn, "taxonomy_version")
        schema_version = _meta(conn, "schema_version")
    finally:
        conn.close()

    return {
        "catalog": {
            "path": str(cfg.db_path),
            "schema_version": schema_version,
            "taxonomy_version": taxonomy_version,
        },
        "stats": {
            "files": stats.files,
            "tracks": stats.tracks,
            "missing": stats.missing,
            "errors": stats.errors,
            "total_duration": stats.total_duration,
            "by_extension": [{"ext": ext, "total": total} for ext, total in stats.by_extension],
            "coverage": [
                {"label": label, "filled": filled, "base": base}
                for label, filled, base in stats.coverage
            ],
        },
        "classification": {
            "genres_active": genres_active,
            "classified": classified,
            "unclassified": max(stats.tracks - classified, 0),
            "distribution": genre_distribution,
        },
        "duplicates": {"groups": dup_groups, "total": sum(g["total"] for g in dup_groups)},
        "versions": {"counts": versions},
        "analysis": {"files": analyzed, "backends": backends},
        "embeddings": {"files": embedded, "models": models, "proposed": proposed},
        "fingerprints": fingerprints,
        "apply": {"batches": batches},
    }


def tracks(cfg: Config, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Lista/busca faixas (query vazia devolve as primeiras `limit`)."""
    conn = _connect(cfg)
    try:
        rows = report.search(conn, query.strip(), limit=limit)
    finally:
        conn.close()
    return [asdict(row) for row in rows]


def duplicates(cfg: Config, limit: int = 50) -> dict[str, Any]:
    """Grupos de duplicatas com metadados dos membros e keeper."""
    conn = _connect(cfg)
    try:
        by_kind = [
            {"kind": str(row["kind"]), "total": int(row["total"])}
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS total FROM dup_groups GROUP BY kind ORDER BY kind"
            )
        ]
        groups: list[dict[str, Any]] = []
        for row in conn.execute(
            "SELECT g.id AS id, g.kind AS kind, g.key AS key, COUNT(m.file_id) AS members"
            " FROM dup_groups g JOIN dup_members m ON m.group_id = g.id"
            " GROUP BY g.id ORDER BY members DESC, g.kind LIMIT ?",
            (limit,),
        ):
            group_id = int(row["id"])
            members = [
                {"path": str(member["path"]), "is_keeper": bool(member["is_keeper"])}
                for member in conn.execute(
                    "SELECT f.path AS path, m.is_keeper AS is_keeper"
                    " FROM dup_members m JOIN files f ON f.id = m.file_id"
                    " WHERE m.group_id = ? ORDER BY m.is_keeper DESC, f.path",
                    (group_id,),
                )
            ]
            groups.append(
                {
                    "kind": str(row["kind"]),
                    "key": str(row["key"]),
                    "members": members,
                }
            )
        total = _scalar(conn, "SELECT COUNT(*) FROM dup_groups")
    finally:
        conn.close()
    return {"by_kind": by_kind, "groups": groups, "total": total}


def versions(cfg: Config, limit: int = 50) -> dict[str, Any]:
    """Distribuicao de versoes classificadas e amostra de arquivos."""
    conn = _connect(cfg)
    try:
        counts = [
            {"version": str(row["version"]), "total": int(row["total"])}
            for row in conn.execute(
                "SELECT version, COUNT(*) AS total FROM file_versions"
                " GROUP BY version ORDER BY total DESC, version"
            )
        ]
        samples = [
            {
                "path": str(row["path"]),
                "version": str(row["version"]),
                "source": str(row["source"]),
                "confidence": str(row["confidence"]),
            }
            for row in conn.execute(
                "SELECT f.path AS path, v.version AS version, v.source AS source,"
                " v.confidence AS confidence"
                " FROM file_versions v JOIN files f ON f.id = v.file_id"
                " ORDER BY f.path LIMIT ?",
                (limit,),
            )
        ]
        total = _scalar(conn, "SELECT COUNT(*) FROM file_versions")
    finally:
        conn.close()
    return {"counts": counts, "samples": samples, "total": total}


def integrations(cfg: Config) -> dict[str, Any]:
    """Integridade dos bancos DJ configurados (Rekordbox/Serato)."""
    reports: list[dict[str, Any]] = []
    for name in integrations_base.SOFTWARES:
        try:
            report_data = integrations_base.dj_status(cfg, name)
        except integrations_base.IntegrationUnavailable as exc:
            reports.append({"software": name, "available": False, "error": str(exc)})
            continue
        reports.append(
            {
                "software": name,
                "available": True,
                "total": report_data.total,
                "resolved": report_data.resolved,
                "missing": report_data.missing,
                "samples": list(report_data.samples),
            }
        )
    return {"software": list(integrations_base.SOFTWARES), "reports": reports}


def capabilities() -> dict[str, Any]:
    """Descreve funcionalidades, pipeline e politicas de seguranca da ferramenta."""
    return {
        "pipeline": list(PIPELINE),
        "commands": list(COMMANDS),
        "safety": list(SAFETY),
    }
