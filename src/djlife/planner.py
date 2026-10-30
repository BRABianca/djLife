from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from djlife.scanner import extended

DEFAULT_UNKNOWN_DIR = "_NaoClassificado"
UNKNOWN_ARTIST = "_Desconhecido"

STATUS_READY = "ready"
STATUS_EXISTS = "exists"
STATUS_CONFLICT = "conflict"
STATUS_UNCLASSIFIED = "unclassified"

CONFIDENCE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PlanItem:
    track_id: int
    file_id: int
    src: Path
    dst: Path | None
    genre: str
    subgenre: str
    status: str


@dataclass(frozen=True)
class Plan:
    target: Path
    strategy: str
    items: tuple[PlanItem, ...]

    def count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def by_genre(self) -> list[tuple[str, int]]:
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.genre] = totals.get(item.genre, 0) + 1
        return sorted(totals.items(), key=lambda entry: (-entry[1], entry[0]))


def _sanitize(value: str) -> str:
    cleaned = _INVALID.sub("_", value)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned.rstrip(". ")


def render_relative(template: str, fields: dict[str, str]) -> Path:
    safe = {key: _sanitize(value) for key, value in fields.items()}
    try:
        rendered = template.format_map(safe)
    except KeyError as exc:
        raise ValueError(f"Placeholder desconhecido no template: {exc}") from exc
    parts = [part for part in rendered.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    if not parts:
        raise ValueError("Template de caminho resultou em caminho vazio.")
    return Path(*parts)


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(extended(left), extended(right))
    except OSError:
        return False


def _unique(dst: Path, taken: set[str]) -> Path:
    key = str(dst).casefold()
    if key not in taken:
        taken.add(key)
        return dst
    stem, suffix, parent = dst.stem, dst.suffix, dst.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        candidate_key = str(candidate).casefold()
        if candidate_key not in taken:
            taken.add(candidate_key)
            return candidate
        counter += 1


@dataclass(frozen=True)
class _Genre:
    id: int
    slug: str
    name: str
    parent_id: int | None
    level: int


def _genre_index(conn: sqlite3.Connection) -> dict[int, _Genre]:
    return {
        int(row["id"]): _Genre(
            id=int(row["id"]),
            slug=str(row["slug"]),
            name=str(row["name"]),
            parent_id=int(row["parent_id"]) if row["parent_id"] is not None else None,
            level=int(row["level"]),
        )
        for row in conn.execute("SELECT id, slug, name, parent_id, level FROM genres")
    }


def _root_and_leaf(genres: dict[int, _Genre], genre_id: int) -> tuple[str, str]:
    node = genres.get(genre_id)
    if node is None:
        return "", ""
    leaf = node
    while node.parent_id is not None and node.parent_id in genres:
        node = genres[node.parent_id]
    subgenre = leaf.name if leaf.level > 0 else ""
    return node.name, subgenre


def _classifications(conn: sqlite3.Connection) -> dict[int, list[tuple[int, str]]]:
    result: dict[int, list[tuple[int, str]]] = {}
    for row in conn.execute("SELECT track_id, genre_id, confidence FROM track_genres"):
        result.setdefault(int(row["track_id"]), []).append(
            (int(row["genre_id"]), str(row["confidence"]))
        )
    return result


def _primary(entries: list[tuple[int, str]], genres: dict[int, _Genre]) -> int:
    def key(entry: tuple[int, str]) -> tuple[int, int, int]:
        genre_id, confidence = entry
        node = genres.get(genre_id)
        level = node.level if node is not None else 0
        return (CONFIDENCE_ORDER.get(confidence, 9), -level, genre_id)

    return min(entries, key=key)[0]


def build_plan(
    conn: sqlite3.Connection,
    *,
    target: Path,
    template: str,
    unknown_dir: str,
    strategy: str,
) -> Plan:
    target = Path(target)
    genres = _genre_index(conn)
    classifications = _classifications(conn)
    taken: set[str] = set()
    items: list[PlanItem] = []

    sql = (
        "SELECT t.id AS track_id, t.file_id, t.title, t.artist, t.album, f.path, f.ext"
        " FROM tracks t JOIN files f ON f.id = t.file_id"
        " WHERE f.is_missing = 0 ORDER BY t.id"
    )
    for row in conn.execute(sql):
        track_id = int(row["track_id"])
        file_id = int(row["file_id"])
        src = Path(str(row["path"]))
        entries = classifications.get(track_id)

        if not entries:
            items.append(
                PlanItem(track_id, file_id, src, None, unknown_dir, "", STATUS_UNCLASSIFIED)
            )
            continue

        genre_name, subgenre = _root_and_leaf(genres, _primary(entries, genres))
        ext = str(row["ext"] or "")
        title = str(row["title"] or "") or src.stem
        fields = {
            "genre": genre_name or unknown_dir,
            "subgenre": subgenre,
            "artist": str(row["artist"] or "") or UNKNOWN_ARTIST,
            "title": title,
            "album": str(row["album"] or ""),
            "ext": ext,
        }
        relative = render_relative(template, fields)
        if ext and not relative.name.lower().endswith(f".{ext.lower()}"):
            relative = relative.with_name(f"{relative.name}.{ext}")
        candidate = _unique(target / relative, taken)

        if candidate.exists():
            status = STATUS_EXISTS if _same_file(src, candidate) else STATUS_CONFLICT
        else:
            status = STATUS_READY
        items.append(
            PlanItem(track_id, file_id, src, candidate, genre_name or unknown_dir, subgenre, status)
        )

    return Plan(target=target, strategy=strategy, items=tuple(items))
