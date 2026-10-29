from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from djlife.integrations.base import (
    SOFTWARE_SERATO,
    DjTrack,
    IntegrationUnavailable,
    IntegrityReport,
    RelinkPlan,
    RelinkResult,
    backup_database,
    integrity_report,
)

ASSET_TABLE = "asset"
PATH_COLUMNS = ("portable_id", "path", "file_path", "location", "file_name", "filename")
NAME_COLUMNS = ("file_name", "filename", "name", "title")
ARTIST_COLUMNS = ("artist",)


def _connect(db_path: Path, *, readonly: bool) -> sqlite3.Connection:
    source = Path(db_path)
    if not source.exists():
        raise IntegrationUnavailable(f"banco Serato inexistente: {source}")
    conn = _connect_readonly(source) if readonly else sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_readonly(source: Path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f"{source.absolute().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA schema_version").fetchone()
    except sqlite3.Error:
        conn = sqlite3.connect(source)
        conn.execute("PRAGMA query_only = ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise IntegrationUnavailable(f"tabela {table!r} ausente no master.sqlite")
    return tuple(str(row["name"]) for row in rows)


def _pick(columns: tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.lower(): name for name in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _pick_path_column(columns: tuple[str, ...]) -> str:
    column = _pick(columns, PATH_COLUMNS)
    if column is None:
        raise IntegrationUnavailable(
            f"nenhuma coluna de caminho encontrada em {ASSET_TABLE}: {', '.join(PATH_COLUMNS)}"
        )
    return column


def _resolve(stored: str, roots: tuple[Path, ...]) -> Path:
    candidate = Path(stored)
    if candidate.is_absolute():
        return candidate
    for root in roots:
        joined = Path(root) / stored
        if joined.exists():
            return joined
    return Path(roots[0]) / stored if roots else candidate


def to_stored(new_abs: str, original: str, roots: tuple[Path, ...] = ()) -> str:
    """Converte um caminho absoluto para a representacao armazenada no Serato."""
    if Path(original).is_absolute():
        return new_abs
    for root in roots:
        rel = os.path.relpath(new_abs, root)
        if not rel.startswith(".."):
            return rel.replace("\\", "/")
    return new_abs


def read_tracks(db_path: Path, *, roots: tuple[Path, ...] = ()) -> tuple[DjTrack, ...]:
    """Le a biblioteca do Serato DJ 4.x (master.sqlite) em modo somente leitura."""
    conn = _connect(db_path, readonly=True)
    try:
        columns = _columns(conn, ASSET_TABLE)
        path_col = _pick_path_column(columns)
        name_col = _pick(columns, NAME_COLUMNS)
        artist_col = _pick(columns, ARTIST_COLUMNS)
        selected = ", ".join(f'"{col}"' for col in (path_col, name_col, artist_col) if col)
        tracks: list[DjTrack] = []
        for row in conn.execute(f"SELECT rowid AS rid, {selected} FROM {ASSET_TABLE}"):
            stored = row[path_col]
            if not stored:
                continue
            resolved = _resolve(str(stored), roots)
            name = row[name_col] if name_col else None
            artist = row[artist_col] if artist_col else None
            tracks.append(
                DjTrack(
                    software=SOFTWARE_SERATO,
                    ref_id=str(row["rid"]),
                    stored=str(stored),
                    path=str(resolved),
                    title=str(name) if name else None,
                    artist=str(artist) if artist else None,
                    exists=resolved.exists(),
                )
            )
        return tuple(tracks)
    finally:
        conn.close()


def status(db_path: Path, *, roots: tuple[Path, ...] = ()) -> IntegrityReport:
    return integrity_report(SOFTWARE_SERATO, read_tracks(db_path, roots=roots))


def relink(
    db_path: Path,
    plan: RelinkPlan,
    *,
    roots: tuple[Path, ...] = (),
    apply: bool = False,
) -> RelinkResult:
    """Atualiza a coluna de caminho dos assets cujos arquivos foram movidos pelo djLife."""
    if not apply or plan.count == 0:
        return RelinkResult(software=SOFTWARE_SERATO, applied=0)

    backup = backup_database(db_path)
    conn = _connect(db_path, readonly=False)
    try:
        columns = _columns(conn, ASSET_TABLE)
        path_col = _pick_path_column(columns)
        name_col = _pick(columns, NAME_COLUMNS)
        by_id = {change.ref_id: change for change in plan.changes}
        applied = 0
        errors = 0
        for row in conn.execute(f"SELECT rowid AS rid FROM {ASSET_TABLE}"):
            change = by_id.get(str(row["rid"]))
            if change is None:
                continue
            conn.execute(
                f'UPDATE {ASSET_TABLE} SET "{path_col}" = ? WHERE rowid = ?',
                (change.new, row["rid"]),
            )
            if name_col and name_col != path_col:
                conn.execute(
                    f'UPDATE {ASSET_TABLE} SET "{name_col}" = ? WHERE rowid = ?',
                    (Path(change.new).name, row["rid"]),
                )
            applied += 1
        conn.commit()
    except sqlite3.Error:
        errors = 1
        applied = 0
        conn.rollback()
    finally:
        conn.close()

    after = status(db_path, roots=roots) if errors == 0 else None
    return RelinkResult(
        software=SOFTWARE_SERATO, applied=applied, backup=backup, errors=errors, after=after
    )
