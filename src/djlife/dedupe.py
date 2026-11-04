from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from djlife.scanner import utcnow

HASH_KIND = "hash"
FINGERPRINT_KIND = "fingerprint"

ISRC_KEYS = frozenset({"tsrc", "isrc", "----:com.apple.itunes:isrc"})
MBID_KEYS = frozenset(
    {
        "musicbrainz_trackid",
        "----:com.apple.itunes:musicbrainz track id",
        "----:com.apple.itunes:musicbrainz_trackid",
    }
)

# Menor = melhor. Usado para escolher o keeper (arquivo canonico) do grupo.
EXT_QUALITY = {"flac": 0, "wav": 1, "aiff": 2, "aif": 2, "alac": 3, "m4a": 4, "ogg": 5, "opus": 5}


class FingerprintUnavailable(RuntimeError):
    """Chromaprint (pyacoustid + fpcalc) indisponivel no ambiente."""


@dataclass(frozen=True)
class DupMember:
    file_id: int
    path: str
    ext: str
    is_keeper: bool


@dataclass(frozen=True)
class DupGroup:
    kind: str
    key: str
    members: tuple[DupMember, ...]


@dataclass(frozen=True)
class DupResult:
    groups: tuple[DupGroup, ...]
    redundant: int

    @property
    def by_kind(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for group in self.groups:
            counts[group.kind] = counts.get(group.kind, 0) + 1
        return sorted(counts.items(), key=lambda item: item[0])


@dataclass(frozen=True)
class _Candidate:
    file_id: int
    path: str
    ext: str
    hash: str | None
    duration: float | None

    def keeper_sort(self) -> tuple[int, int, int, str]:
        quality = EXT_QUALITY.get(self.ext, 9)
        return (quality, -int(self.duration or 0), len(self.path), self.path)


def _candidates(conn: sqlite3.Connection) -> dict[int, _Candidate]:
    rows = conn.execute(
        "SELECT f.id, f.path, f.ext, f.hash,"
        " (SELECT t.duration FROM tracks t WHERE t.file_id = f.id) AS duration"
        " FROM files f WHERE f.is_missing = 0"
    )
    return {
        int(row["id"]): _Candidate(
            file_id=int(row["id"]),
            path=str(row["path"]),
            ext=str(row["ext"]),
            hash=row["hash"],
            duration=row["duration"],
        )
        for row in rows
    }


def _hash_buckets(candidates: dict[int, _Candidate]) -> list[tuple[str, list[int]]]:
    buckets: dict[str, list[int]] = {}
    for candidate in candidates.values():
        if candidate.hash:
            buckets.setdefault(candidate.hash, []).append(candidate.file_id)
    return [(key, ids) for key, ids in buckets.items() if len(ids) >= 2]


def _fingerprint_buckets(
    conn: sqlite3.Connection, candidates: dict[int, _Candidate]
) -> list[tuple[str, list[int]]]:
    buckets: dict[str, list[int]] = {}
    for row in conn.execute("SELECT file_id, fingerprint FROM fingerprints"):
        file_id = int(row["file_id"])
        if file_id in candidates:
            buckets.setdefault(str(row["fingerprint"]), []).append(file_id)
    return [(key, ids) for key, ids in buckets.items() if len(ids) >= 2]


def _external_buckets(
    conn: sqlite3.Connection, candidates: dict[int, _Candidate]
) -> list[tuple[str, str, list[int]]]:
    buckets: dict[tuple[str, str], list[int]] = {}
    for row in conn.execute(
        "SELECT file_id, key, value FROM tags WHERE value IS NOT NULL AND value <> ''"
    ):
        file_id = int(row["file_id"])
        if file_id not in candidates:
            continue
        key = str(row["key"]).lower()
        value = str(row["value"]).strip()
        if not value:
            continue
        if key in ISRC_KEYS:
            buckets.setdefault(("isrc", value.upper()), []).append(file_id)
        elif key in MBID_KEYS or (key.startswith("ufid:") and "musicbrainz" in key):
            buckets.setdefault(("mbid", value.lower()), []).append(file_id)
    return [(kind, key, ids) for (kind, key), ids in buckets.items() if len(ids) >= 2]


def _write_groups(
    conn: sqlite3.Connection,
    now: str,
    entries: Iterable[tuple[str, str, list[int]]],
    candidates: dict[int, _Candidate],
) -> list[DupGroup]:
    groups: list[DupGroup] = []
    for kind, key, ids in entries:
        ordered = sorted(dict.fromkeys(ids))
        keeper_id = min(ordered, key=lambda file_id: candidates[file_id].keeper_sort())
        cursor = conn.execute(
            "INSERT INTO dup_groups(kind, key, created_at) VALUES (?, ?, ?)",
            (kind, key, now),
        )
        group_id = int(cursor.lastrowid or 0)
        members: list[DupMember] = []
        for file_id in ordered:
            is_keeper = file_id == keeper_id
            conn.execute(
                "INSERT INTO dup_members(group_id, file_id, is_keeper) VALUES (?, ?, ?)",
                (group_id, file_id, 1 if is_keeper else 0),
            )
            candidate = candidates[file_id]
            members.append(DupMember(file_id, candidate.path, candidate.ext, is_keeper))
        groups.append(DupGroup(kind, key, tuple(members)))
    return groups


def find_duplicates(conn: sqlite3.Connection, *, use_fingerprint: bool = False) -> DupResult:
    candidates = _candidates(conn)
    entries: list[tuple[str, str, list[int]]] = []
    entries.extend((HASH_KIND, key, ids) for key, ids in _hash_buckets(candidates))
    if use_fingerprint:
        entries.extend(
            (FINGERPRINT_KIND, key, ids) for key, ids in _fingerprint_buckets(conn, candidates)
        )
    entries.extend(_external_buckets(conn, candidates))

    conn.execute("DELETE FROM dup_groups")
    groups = _write_groups(conn, utcnow(), entries, candidates)
    conn.commit()

    redundant = {m.file_id for g in groups for m in g.members if not m.is_keeper}
    return DupResult(groups=tuple(groups), redundant=len(redundant))


def _load_acoustid() -> object:
    try:
        import acoustid  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise FingerprintUnavailable(
            "pyacoustid nao instalado. Use o extra: pip install -e '.[fingerprint]'."
        ) from exc
    return acoustid


def fingerprint_file(path: Path) -> tuple[float, str]:
    acoustid = _load_acoustid()
    duration, fingerprint = acoustid.fingerprint_file(str(path))  # type: ignore[attr-defined]
    if isinstance(fingerprint, bytes):
        text = fingerprint.decode("utf-8", "replace")
    else:
        text = str(fingerprint)
    return float(duration), text


def compute_fingerprints(
    conn: sqlite3.Connection, file_ids: list[int] | None = None
) -> tuple[int, int]:
    _load_acoustid()
    if file_ids is None:
        rows = list(
            conn.execute(
                "SELECT f.id, f.path FROM files f"
                " LEFT JOIN fingerprints p ON p.file_id = f.id"
                " WHERE f.is_missing = 0 AND p.file_id IS NULL"
            )
        )
    else:
        placeholders = ",".join("?" * len(file_ids))
        rows = list(
            conn.execute(f"SELECT id, path FROM files WHERE id IN ({placeholders})", file_ids)
        )

    now = utcnow()
    computed = 0
    errors = 0
    for row in rows:
        try:
            duration, fingerprint = fingerprint_file(Path(row["path"]))
        except (OSError, ValueError, FingerprintUnavailable) as exc:
            errors += 1
            conn.execute(
                "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
                (row["path"], f"fingerprint: {exc}"),
            )
            continue
        conn.execute(
            "INSERT INTO fingerprints(file_id, fingerprint, duration, source, computed_at)"
            " VALUES (?, ?, ?, 'chromaprint', ?)"
            " ON CONFLICT(file_id) DO UPDATE SET fingerprint = excluded.fingerprint,"
            " duration = excluded.duration, computed_at = excluded.computed_at",
            (row["id"], fingerprint, duration, now),
        )
        computed += 1
    conn.commit()
    return computed, errors
