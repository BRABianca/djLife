from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from djlife.scanner import utcnow

DEFAULT_VERSION = "Original"
DEFAULT_CONFIDENCE = "C"
SOURCE = "rules"

# Ordem = prioridade: o primeiro padrao que casa vence (mais especifico primeiro).
VERSION_RULES: tuple[tuple[str, str, str], ...] = (
    ("Bootleg", r"\bbootleg\b", "A"),
    ("Mashup", r"\bmash[- ]?up\b", "A"),
    ("Instrumental", r"\binstrumental\b", "A"),
    ("Acapella", r"\ba?cc?apella\b", "A"),
    ("Remix", r"\b(remix|rmx|rework|refix|flip|vip)\b", "A"),
    ("Dub", r"\bdub\b", "B"),
    ("Extended", r"\bextended\b", "A"),
    ("Radio", r"\bradio\b", "A"),
    ("Original", r"\boriginal\b", "A"),
)
_COMPILED: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE), confidence)
    for label, pattern, confidence in VERSION_RULES
)


@dataclass(frozen=True)
class VersionResult:
    tracks: int
    classified: int
    counts: tuple[tuple[str, int], ...]


def classify_text(text: str) -> tuple[str, str]:
    for label, pattern, confidence in _COMPILED:
        if pattern.search(text):
            return label, confidence
    return DEFAULT_VERSION, DEFAULT_CONFIDENCE


def _haystack(title: str | None, album: str | None, path: str) -> str:
    stem = Path(path).stem
    return " | ".join(part for part in (title, album, stem) if part)


def classify_versions(conn: sqlite3.Connection) -> VersionResult:
    now = utcnow()
    rows = list(
        conn.execute(
            "SELECT t.id AS track_id, f.id AS file_id, t.title, t.album, f.path"
            " FROM tracks t JOIN files f ON f.id = t.file_id ORDER BY t.id"
        )
    )
    counts: dict[str, int] = {}
    classified = 0
    for row in rows:
        version, confidence = classify_text(_haystack(row["title"], row["album"], row["path"]))
        counts[version] = counts.get(version, 0) + 1
        conn.execute(
            "INSERT INTO file_versions(file_id, version, source, confidence, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(file_id) DO UPDATE SET version = excluded.version,"
            " source = excluded.source, confidence = excluded.confidence,"
            " updated_at = excluded.updated_at",
            (row["file_id"], version, SOURCE, confidence, now),
        )
        classified += 1
    conn.commit()
    ordered = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    return VersionResult(tracks=len(rows), classified=classified, counts=ordered)
