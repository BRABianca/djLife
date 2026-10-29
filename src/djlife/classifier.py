from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from djlife.scanner import utcnow
from djlife.taxonomy import Taxonomy, normalize

GENRE_TAG_KEYS = ("tcon", "genre", "\u00a9gen")
LAYERS = ("tags", "rules")
RULE_FIELDS = ("any", "title", "artist", "album", "path")
TAG_CONFIDENCE = "A"
DEFAULT_RULE_CONFIDENCE = "B"
_SPLIT = re.compile(r"[;,]")


@dataclass(frozen=True)
class Rule:
    name: str
    field: str
    pattern: re.Pattern[str]
    genre: str
    confidence: str = DEFAULT_RULE_CONFIDENCE


@dataclass(frozen=True)
class ClassifyResult:
    tracks: int
    tagged: int
    ruled: int
    unresolved: int
    inserted: int


def load_rules(path: Path | str) -> tuple[Rule, ...]:
    source = Path(path)
    if not source.exists():
        return ()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Regras invalidas: {source}")
    raw = data.get("rules") or []
    if not isinstance(raw, list):
        raise ValueError("'rules' deve ser uma lista.")

    rules: list[Rule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Cada regra deve ser um mapa.")
        field = str(entry.get("field", "any")).lower()
        if field not in RULE_FIELDS:
            raise ValueError(f"Regra com 'field' invalido: {field!r}.")
        rules.append(
            Rule(
                name=str(entry.get("name", entry["genre"])),
                field=field,
                pattern=re.compile(str(entry["match"]), re.IGNORECASE),
                genre=str(entry["genre"]),
                confidence=str(entry.get("confidence", DEFAULT_RULE_CONFIDENCE)),
            )
        )
    return tuple(rules)


def _genre_tags(conn: sqlite3.Connection) -> dict[int, list[str]]:
    placeholders = ",".join("?" * len(GENRE_TAG_KEYS))
    result: dict[int, list[str]] = {}
    for row in conn.execute(
        f"SELECT file_id, value FROM tags WHERE LOWER(key) IN ({placeholders})",
        GENRE_TAG_KEYS,
    ):
        if row["value"]:
            result.setdefault(int(row["file_id"]), []).append(str(row["value"]))
    return result


def _match(rule: Rule, fields: dict[str, str]) -> bool:
    if rule.field == "any":
        return any(rule.pattern.search(value) for value in fields.values() if value)
    value = fields.get(rule.field, "")
    return bool(value) and rule.pattern.search(value) is not None


def classify(
    conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    rules: tuple[Rule, ...] = (),
    layers: tuple[str, ...] = LAYERS,
) -> ClassifyResult:
    tracks = list(
        conn.execute(
            "SELECT t.id AS track_id, t.title, t.artist, t.album, f.path, f.id AS file_id"
            " FROM tracks t JOIN files f ON f.id = t.file_id ORDER BY t.id"
        )
    )
    genre_ids = {
        str(row["slug"]): int(row["id"]) for row in conn.execute("SELECT id, slug FROM genres")
    }
    tag_map = _genre_tags(conn) if "tags" in layers else {}

    pending: list[tuple[int, int, str, str]] = []
    resolved: set[int] = set()
    tag_tracks: set[int] = set()
    rule_tracks: set[int] = set()

    for row in tracks:
        track_id = int(row["track_id"])
        found = False
        if "tags" in layers:
            for raw in tag_map.get(int(row["file_id"]), []):
                for token in _SPLIT.split(raw):
                    slug = taxonomy.alias_index.get(normalize(token))
                    genre_id = genre_ids.get(slug) if slug else None
                    if genre_id is not None:
                        pending.append((track_id, genre_id, "tags", TAG_CONFIDENCE))
                        tag_tracks.add(track_id)
                        found = True
        if "rules" in layers:
            fields = {
                "title": str(row["title"] or ""),
                "artist": str(row["artist"] or ""),
                "album": str(row["album"] or ""),
                "path": str(row["path"]),
            }
            for rule in rules:
                genre_id = genre_ids.get(rule.genre)
                if genre_id is not None and _match(rule, fields):
                    pending.append((track_id, genre_id, "rules", rule.confidence))
                    rule_tracks.add(track_id)
                    found = True
        if found:
            resolved.add(track_id)

    now = utcnow()
    inserted = 0
    for track_id, genre_id, source, confidence in pending:
        cursor = conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
            " VALUES (?, ?, ?, ?, NULL, ?)"
            " ON CONFLICT(track_id, genre_id, source) DO NOTHING",
            (track_id, genre_id, source, confidence, now),
        )
        if cursor.rowcount > 0:
            inserted += cursor.rowcount
    conn.commit()

    return ClassifyResult(
        tracks=len(tracks),
        tagged=len(tag_tracks),
        ruled=len(rule_tracks),
        unresolved=len(tracks) - len(resolved),
        inserted=inserted,
    )
