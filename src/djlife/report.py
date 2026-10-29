from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, fields
from pathlib import Path

BPM_KEYS = frozenset({"tbpm", "bpm", "tmpo"})
KEY_KEYS = frozenset({"tkey", "initialkey", "----:com.apple.itunes:initialkey"})
GENRE_KEYS = frozenset({"tcon", "genre", "\u00a9gen"})

_TRACK_SELECT = """
    SELECT t.file_id, f.path, f.ext, f.size, f.is_missing,
           t.duration, t.title, t.artist, t.album
    FROM tracks t
    JOIN files f ON f.id = t.file_id
"""


@dataclass(frozen=True)
class TrackRow:
    path: str
    ext: str
    size: int
    duration: float | None
    title: str | None
    artist: str | None
    album: str | None
    bpm: str | None
    key: str | None
    genre: str | None
    bpm_analysis: float | None
    key_camelot: str | None
    is_missing: bool


@dataclass(frozen=True)
class Stats:
    files: int
    tracks: int
    missing: int
    errors: int
    total_duration: float
    by_extension: list[tuple[str, int]]
    coverage: list[tuple[str, int, int]]


def _tag_map(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for row in conn.execute("SELECT file_id, key, value FROM tags"):
        result.setdefault(row["file_id"], {})[row["key"].lower()] = row["value"] or ""
    return result


def _analysis_map(conn: sqlite3.Connection) -> dict[int, tuple[float | None, str | None]]:
    """BPM/tonalidade da analise mais recente de cada arquivo."""
    result: dict[int, tuple[float | None, str | None]] = {}
    for row in conn.execute(
        "SELECT file_id, bpm, key_camelot FROM audio_analysis ORDER BY analyzed_at DESC"
    ):
        file_id = int(row["file_id"])
        if file_id not in result:
            result[file_id] = (row["bpm"], row["key_camelot"])
    return result


def _pick(tags: dict[str, str], keys: frozenset[str]) -> str | None:
    for key in keys:
        if key in tags:
            return tags[key]
    return None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> list[TrackRow]:
    tag_map = _tag_map(conn)
    analysis_map = _analysis_map(conn)
    rows: list[TrackRow] = []
    for row in conn.execute(sql, params):
        tags = tag_map.get(row["file_id"], {})
        analysis = analysis_map.get(row["file_id"], (None, None))
        rows.append(
            TrackRow(
                path=row["path"],
                ext=row["ext"],
                size=row["size"],
                duration=row["duration"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                bpm=_pick(tags, BPM_KEYS),
                key=_pick(tags, KEY_KEYS),
                genre=_pick(tags, GENRE_KEYS),
                bpm_analysis=analysis[0],
                key_camelot=analysis[1],
                is_missing=bool(row["is_missing"]),
            )
        )
    return rows


def fetch_tracks(conn: sqlite3.Connection) -> list[TrackRow]:
    return _rows(conn, _TRACK_SELECT + " ORDER BY f.path")


def search(conn: sqlite3.Connection, term: str, limit: int = 50) -> list[TrackRow]:
    pattern = f"%{term}%"
    sql = _TRACK_SELECT + (
        " WHERE t.title LIKE ? OR t.artist LIKE ? OR t.album LIKE ? OR f.path LIKE ?"
        " ORDER BY f.path LIMIT ?"
    )
    return _rows(conn, sql, (pattern, pattern, pattern, pattern, limit))


def _count_value(conn: sqlite3.Connection, column: str) -> int:
    sql = f"SELECT COUNT(*) FROM tracks WHERE {column} IS NOT NULL AND {column} <> ''"
    return int(conn.execute(sql).fetchone()[0])


def _count_files_with_tags(conn: sqlite3.Connection, keys: frozenset[str]) -> int:
    placeholders = ",".join("?" * len(keys))
    sql = (
        "SELECT COUNT(DISTINCT file_id) FROM tags"
        f" WHERE LOWER(key) IN ({placeholders})"
    )
    return int(conn.execute(sql, tuple(keys)).fetchone()[0])


def _count_analysis(conn: sqlite3.Connection, column: str) -> int:
    sql = f"SELECT COUNT(DISTINCT file_id) FROM audio_analysis WHERE {column} IS NOT NULL"
    return int(conn.execute(sql).fetchone()[0])


def collect_stats(conn: sqlite3.Connection) -> Stats:
    files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
    missing = int(conn.execute("SELECT COUNT(*) FROM files WHERE is_missing = 1").fetchone()[0])
    tracks = int(conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0])
    errors = int(conn.execute("SELECT COUNT(*) FROM scan_errors").fetchone()[0])
    total = float(conn.execute("SELECT COALESCE(SUM(duration), 0) FROM tracks").fetchone()[0])
    by_extension = [
        (row[0], int(row[1]))
        for row in conn.execute(
            "SELECT ext, COUNT(*) AS total FROM files GROUP BY ext ORDER BY total DESC, ext"
        )
    ]
    coverage = [
        ("Titulo", _count_value(conn, "title"), tracks),
        ("Artista", _count_value(conn, "artist"), tracks),
        ("Album", _count_value(conn, "album"), tracks),
        ("BPM", _count_files_with_tags(conn, BPM_KEYS), files),
        ("Tonalidade", _count_files_with_tags(conn, KEY_KEYS), files),
        ("Genero (tag)", _count_files_with_tags(conn, GENRE_KEYS), files),
        ("BPM (analise)", _count_analysis(conn, "bpm"), files),
        ("Tonalidade (analise)", _count_analysis(conn, "key_camelot"), files),
    ]
    return Stats(files, tracks, missing, errors, total, by_extension, coverage)


def _write_csv(rows: list[TrackRow], path: Path) -> None:
    fieldnames = [field.name for field in fields(TrackRow)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_json(rows: list[TrackRow], path: Path) -> None:
    payload = json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")


def export(conn: sqlite3.Connection, path: Path, fmt: str | None = None) -> int:
    rows = fetch_tracks(conn)
    suffix = (fmt or path.suffix.lstrip(".")).lower()
    if suffix == "csv":
        _write_csv(rows, path)
    elif suffix == "json":
        _write_json(rows, path)
    else:
        raise ValueError(f"Formato nao suportado: {suffix!r}. Use csv ou json.")
    return len(rows)
