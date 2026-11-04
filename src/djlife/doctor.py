"""Auditoria do ambiente e da organizacao do catalogo.

Reune verificacoes baratas e offline (sem rede) que ajudam a diagnosticar por que algo nao
funciona: estado do catalogo SQLite, PRAGMAs, integridade, raizes da biblioteca, extras
opcionais do Python e binarios externos. Somente leitura: nada e escrito.
"""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
from dataclasses import dataclass

from djlife import db
from djlife import license as license_mod
from djlife.config import Config

OK = "ok"
WARN = "warn"
FAIL = "fail"

# (nome do extra, modulo importavel) para o diagnostico de extras opcionais.
MODULES: tuple[tuple[str, str], ...] = (
    ("analysis", "librosa"),
    ("ml", "torch"),
    ("ml", "transformers"),
    ("muq", "muq"),
    ("essentia", "essentia"),
    ("fingerprint", "pyacoustid"),
    ("rekordbox", "pyrekordbox"),
    ("premium", "yt_dlp"),
)

# Binarios externos usados por extras especificos.
BINARIES: tuple[tuple[str, str], ...] = (
    ("fingerprint", "fpcalc"),
    ("analysis", "ffmpeg"),
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _pragma(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(f"PRAGMA {name}").fetchone()
    return str(row[0]) if row else ""


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def _check_catalog(cfg: Config) -> list[Check]:
    path = cfg.db_path
    if not path.exists():
        return [
            Check("catalogo", FAIL, f"nao encontrado: {path} (rode `djlife scan`)."),
        ]

    checks = [Check("catalogo", OK, str(path))]
    try:
        conn = db.connect(path, create=False)
    except sqlite3.DatabaseError as exc:
        return [*checks, Check("abertura", FAIL, str(exc))]

    try:
        version = db.schema_version(conn)
        status = OK if version == db.SCHEMA_VERSION else WARN
        checks.append(Check("schema", status, f"v{version} (esperado v{db.SCHEMA_VERSION})"))

        journal = _pragma(conn, "journal_mode").lower()
        checks.append(
            Check("journal_mode", OK if journal == "wal" else WARN, journal or "desconhecido")
        )

        foreign_keys = _pragma(conn, "foreign_keys")
        checks.append(
            Check("foreign_keys", OK if foreign_keys == "1" else WARN, foreign_keys or "0")
        )

        integrity = _pragma(conn, "quick_check").lower()
        checks.append(Check("integridade", OK if integrity == "ok" else FAIL, integrity))

        files = _scalar(conn, "SELECT COUNT(*) FROM files")
        tracks = _scalar(conn, "SELECT COUNT(*) FROM tracks")
        missing = _scalar(conn, "SELECT COUNT(*) FROM files WHERE is_missing = 1")
        errors = _scalar(conn, "SELECT COUNT(*) FROM scan_errors")
        checks.append(Check("conteudo", OK, f"{files} arquivos, {tracks} faixas"))
        checks.append(
            Check("ausentes", WARN if missing else OK, f"{missing} arquivos fora do disco")
        )
        checks.append(Check("erros de scan", WARN if errors else OK, f"{errors} registros"))
    finally:
        conn.close()
    return checks


def _check_library(cfg: Config) -> list[Check]:
    checks: list[Check] = []
    roots = cfg.library.roots
    if not roots:
        checks.append(Check("raizes", WARN, "library.roots vazio (use argumento no `scan`)."))
    for root in roots:
        if root.exists():
            checks.append(Check(f"raiz: {root}", OK, "existe"))
        else:
            checks.append(Check(f"raiz: {root}", WARN, "nao encontrada"))

    target = cfg.files.target
    if target is None:
        checks.append(
            Check("files.target", WARN, "nao definido (informe na config ou use --target).")
        )
    else:
        present = target.exists()
        label = "existe" if present else "nao existe"
        checks.append(Check("files.target", OK if present else WARN, f"{target} ({label})"))
    return checks


def _check_extras() -> list[Check]:
    checks: list[Check] = []
    for extra, module in MODULES:
        present = _module_available(module)
        checks.append(
            Check(
                f"extra {extra}: {module}",
                OK if present else WARN,
                "disponivel" if present else f'ausente (pip install -e ".[{extra}]")',
            )
        )
    for extra, binary in BINARIES:
        found = shutil.which(binary)
        checks.append(
            Check(
                f"binario {binary}",
                OK if found else WARN,
                found or f"nao encontrado no PATH (necessario para {extra})",
            )
        )
    return checks


def _check_license(cfg: Config) -> list[Check]:
    checks: list[Check] = []
    public_key = cfg.license.public_key_path
    license_file = cfg.license.license_path
    checks.append(
        Check(
            "license public_key",
            OK if public_key.exists() else WARN,
            str(public_key) if public_key.exists() else f"ausente: {public_key}",
        )
    )
    checks.append(
        Check(
            "license file",
            OK if license_file.exists() else WARN,
            str(license_file) if license_file.exists() else f"ausente: {license_file}",
        )
    )
    status = license_mod.status_from_paths(
        license_path=license_file,
        public_key_path=public_key,
    )
    checks.append(
        Check(
            "license status",
            OK if status.valid else WARN,
            status.reason,
        )
    )
    return checks


def run(cfg: Config) -> list[Check]:
    """Executa todas as verificacoes e devolve a lista consolidada."""
    return [*_check_catalog(cfg), *_check_library(cfg), *_check_extras(), *_check_license(cfg)]
