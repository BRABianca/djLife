from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from djlife.config import Config
from djlife.scanner import extended

SOFTWARE_REKORDBOX = "rekordbox"
SOFTWARE_SERATO = "serato"
SOFTWARES = (SOFTWARE_REKORDBOX, SOFTWARE_SERATO)


class IntegrationUnavailable(RuntimeError):
    """Dependencia opcional ausente ou banco de terceiro inacessivel."""


def norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def backup_database(path: Path) -> Path:
    source = Path(path)
    if not source.exists():
        raise IntegrationUnavailable(f"banco inexistente: {source}")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest = source.with_name(f"{source.name}.djlife-{stamp}.bak")
    shutil.copy2(extended(source), extended(dest))
    if not dest.exists() or dest.stat().st_size != source.stat().st_size:
        raise IntegrationUnavailable(f"backup incompleto: {dest}")
    return dest


@dataclass(frozen=True)
class DjTrack:
    software: str
    ref_id: str
    stored: str
    path: str
    title: str | None
    artist: str | None
    exists: bool


@dataclass(frozen=True)
class IntegrityReport:
    software: str
    total: int
    resolved: int
    missing: int
    samples: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return self.missing == 0


@dataclass(frozen=True)
class RelinkChange:
    ref_id: str
    old: str
    new: str


@dataclass(frozen=True)
class RelinkPlan:
    software: str
    changes: tuple[RelinkChange, ...]

    @property
    def count(self) -> int:
        return len(self.changes)


@dataclass(frozen=True)
class RelinkResult:
    software: str
    applied: int
    backup: Path | None = None
    errors: int = 0
    after: IntegrityReport | None = None


def integrity_report(software: str, tracks: tuple[DjTrack, ...]) -> IntegrityReport:
    missing = tuple(track.path for track in tracks if not track.exists)
    return IntegrityReport(
        software=software,
        total=len(tracks),
        resolved=len(tracks) - len(missing),
        missing=len(missing),
        samples=missing[:10],
    )


def serato_db_path(cfg: Config) -> Path | None:
    """Resolve o caminho do `master.sqlite` a partir da config (None se ausente)."""
    if cfg.integrations.serato_db is not None:
        return cfg.integrations.serato_db
    base_dir = cfg.integrations.serato_dir
    if base_dir is None:
        return None
    for candidate in (base_dir / "master.sqlite", base_dir / "Library" / "master.sqlite"):
        if candidate.exists():
            return candidate
    return base_dir / "master.sqlite"


def library_roots(cfg: Config) -> tuple[Path, ...]:
    """Raizes usadas para resolver caminhos relativos das bibliotecas DJ."""
    roots = list(cfg.library.roots)
    if cfg.integrations.serato_dir is not None:
        roots.append(cfg.integrations.serato_dir)
    return tuple(roots)


def dj_status(cfg: Config, software: str) -> IntegrityReport:
    """Integridade de um software DJ; levanta `IntegrationUnavailable` se inacessivel."""
    from djlife.integrations import rekordbox, serato

    if software == SOFTWARE_REKORDBOX:
        return rekordbox.status(cfg.integrations.rekordbox_db)
    path = serato_db_path(cfg)
    if path is None:
        raise IntegrationUnavailable("integrations.serato_db nao configurado")
    return serato.status(path, roots=library_roots(cfg))


def _keeper_path(conn: sqlite3.Connection, file_id: int) -> str | None:
    row = conn.execute(
        "SELECT f.path FROM dup_members m"
        " JOIN files f ON f.id = m.file_id"
        " WHERE m.is_keeper = 1 AND m.group_id IN"
        " (SELECT group_id FROM dup_members WHERE file_id = ?)",
        (file_id,),
    ).fetchone()
    return str(row["path"]) if row else None


def resolve_move_mapping(conn: sqlite3.Connection) -> dict[str, str]:
    """Mapeia caminho original -> caminho atual a partir do journal (op=move)."""
    mapping: dict[str, str] = {}
    rows = conn.execute(
        "SELECT strategy, src, dst, file_id FROM journal"
        " WHERE undone = 0 AND op = 'move' AND dst IS NOT NULL"
        " ORDER BY id"
    )
    for row in rows:
        src = str(row["src"])
        target = str(row["dst"])
        file_id = row["file_id"]
        if row["strategy"] == "quarantine" and file_id is not None:
            keeper = _keeper_path(conn, int(file_id))
            if keeper is not None:
                target = keeper
        mapping[norm(src)] = target
    return mapping


def relink_plan(
    software: str,
    tracks: tuple[DjTrack, ...],
    mapping: dict[str, str],
    *,
    convert: Callable[[str, str], str],
) -> RelinkPlan:
    changes: list[RelinkChange] = []
    seen: set[str] = set()
    for track in tracks:
        if track.exists or track.path in seen:
            continue
        target = mapping.get(norm(track.path))
        if target is None:
            continue
        new_stored = convert(target, track.stored)
        if new_stored == track.stored:
            continue
        seen.add(track.path)
        changes.append(RelinkChange(ref_id=track.ref_id, old=track.stored, new=new_stored))
    return RelinkPlan(software=software, changes=tuple(changes))
