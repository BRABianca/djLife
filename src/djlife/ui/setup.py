"""Fluxo de primeiro acesso: selecao da pasta raiz da biblioteca.

O catalogo segue somente leitura; a unica escrita aqui e `library.roots` no arquivo de
configuracao (djlife.toml), feita sob demanda do usuario na tela de boas-vindas.
"""

from __future__ import annotations

import os
import string
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from djlife import config as config_mod
from djlife import db, scanner, tags
from djlife.config import Config


class SetupError(RuntimeError):
    """Falha ao listar diretorios ou gravar a pasta raiz."""


def places() -> list[dict[str, str]]:
    """Locais iniciais de navegacao (unidades no Windows, / e home nos demais)."""
    if os.name == "nt":
        drives = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if Path(root).exists():
                drives.append({"name": root, "path": root})
        return drives
    return [{"name": "/", "path": "/"}, {"name": "home", "path": str(Path.home())}]


def state(cfg: Config, config_path: Path | str) -> dict[str, Any]:
    roots = [str(root) for root in cfg.library.roots]
    return {
        "configured": bool(roots),
        "roots": roots,
        "config_path": str(config_path),
        "catalog": str(cfg.db_path),
        "catalog_exists": cfg.db_path.exists(),
        "places": places(),
    }


def list_directory(raw: str) -> dict[str, Any]:
    target = Path(raw).expanduser()
    if not target.is_dir():
        raise SetupError(f"pasta invalida: {raw}")
    dirs: list[dict[str, str]] = []
    try:
        with os.scandir(scanner.extended(target)) as iterator:
            for entry in iterator:
                if entry.name.startswith((".", "$")):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append({"name": entry.name, "path": str(target / entry.name)})
                except OSError:
                    continue
    except OSError as exc:
        raise SetupError(str(exc)) from exc
    dirs.sort(key=lambda item: item["name"].lower())
    parent = target.parent
    return {
        "path": str(target),
        "parent": str(parent) if parent != target else None,
        "dirs": dirs,
    }


def save_root(config_path: Path | str, raw: str) -> Config:
    target = Path(raw).expanduser()
    if not target.is_dir():
        raise SetupError(f"pasta invalida: {raw}")
    config_mod.update_library_roots(config_path, [str(target)])
    return config_mod.load_config(config_path)


@dataclass
class ScanJob:
    status: str = "running"
    roots: list[str] = field(default_factory=list)
    current: str | None = None
    seen: int = 0
    new: int = 0
    updated: int = 0
    missing: int = 0
    errors: int = 0
    indexed: int = 0
    error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "roots": list(self.roots),
            "current": self.current,
            "seen": self.seen,
            "new": self.new,
            "updated": self.updated,
            "missing": self.missing,
            "errors": self.errors,
            "indexed": self.indexed,
            "error": self.error,
        }


def start_scan(cfg: Config) -> ScanJob:
    job = ScanJob(roots=[str(root) for root in cfg.library.roots])
    if not job.roots:
        raise SetupError("nenhuma pasta raiz configurada")

    def worker() -> None:
        try:
            conn = db.open_catalog(cfg.db_path)
            try:
                for root in cfg.library.roots:
                    job.current = str(root)
                    outcome = scanner.scan(
                        conn,
                        root,
                        extensions=cfg.library.extensions,
                        hash_files=cfg.catalog.hash_files,
                        hash_algorithm=cfg.catalog.hash_algorithm,
                        follow_symlinks=cfg.library.follow_symlinks,
                    )
                    job.seen += outcome.seen
                    job.new += outcome.new
                    job.updated += outcome.updated
                    job.missing += outcome.missing
                    job.errors += outcome.error_count
                    if outcome.changed_ids:
                        indexed, _ = tags.index_tags(conn, outcome.changed_ids)
                        job.indexed += indexed
            finally:
                conn.close()
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.error = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job
