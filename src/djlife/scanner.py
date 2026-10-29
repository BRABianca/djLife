from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

HASH_CHUNK = 1 << 20


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def extended(path: str | os.PathLike[str]) -> str:
    """Prefixa caminhos absolutos longos com \\\\?\\ (somente Windows)."""
    raw = os.fspath(path)
    if os.name != "nt" or not os.path.isabs(raw):
        return raw
    if raw.startswith("\\\\?\\"):
        return raw
    if raw.startswith("\\\\"):
        return "\\\\?\\UNC\\" + raw[2:]
    return "\\\\?\\" + raw


def file_hash(path: Path, algorithm: str = "blake2b") -> str:
    digest = hashlib.new(algorithm)
    with open(extended(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FoundFile:
    path: Path
    size: int
    mtime: float


@dataclass
class ScanOutcome:
    run_id: int
    root: str
    seen: int = 0
    new: int = 0
    updated: int = 0
    missing: int = 0
    error_count: int = 0
    changed_ids: list[int] = field(default_factory=list)


def _ext(path: Path) -> str:
    suffix = path.suffix
    return suffix[1:].lower() if suffix else ""


def iter_audio_files(
    root: Path,
    extensions: frozenset[str],
    *,
    follow_symlinks: bool = False,
    on_error: Callable[[Path, OSError], None] | None = None,
) -> Iterator[FoundFile]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            iterator = os.scandir(extended(directory))
        except OSError as exc:
            if on_error is not None:
                on_error(directory, exc)
            continue
        with iterator:
            for entry in iterator:
                logical = directory / entry.name
                try:
                    if entry.is_dir(follow_symlinks=follow_symlinks):
                        stack.append(logical)
                        continue
                    if not entry.is_file(follow_symlinks=follow_symlinks):
                        continue
                    if _ext(logical) not in extensions:
                        continue
                    stat = entry.stat(follow_symlinks=follow_symlinks)
                except OSError as exc:
                    if on_error is not None:
                        on_error(logical, exc)
                    continue
                yield FoundFile(logical, stat.st_size, stat.st_mtime)


def scan(
    conn: sqlite3.Connection,
    root: Path,
    *,
    extensions: tuple[str, ...],
    hash_files: bool = True,
    hash_algorithm: str = "blake2b",
    follow_symlinks: bool = False,
) -> ScanOutcome:
    root = Path(root).resolve()
    now = utcnow()
    run_id = cast(
        int,
        conn.execute(
            "INSERT INTO scan_runs(root, started_at, status) VALUES (?, ?, 'running')",
            (str(root), now),
        ).lastrowid,
    )
    conn.commit()

    prefix = str(root) + os.sep
    existing = {
        row["path"]: (row["id"], row["size"], row["mtime"], row["is_missing"])
        for row in conn.execute(
            "SELECT id, path, size, mtime, is_missing FROM files WHERE substr(path, 1, ?) = ?",
            (len(prefix), prefix),
        )
    }

    outcome = ScanOutcome(run_id=run_id, root=str(root))
    seen: set[str] = set()

    def record_error(path: Path, exc: OSError) -> None:
        outcome.error_count += 1
        conn.execute(
            "INSERT INTO scan_errors(run_id, path, message) VALUES (?, ?, ?)",
            (run_id, str(path), str(exc)),
        )

    for found in iter_audio_files(
        root, frozenset(extensions), follow_symlinks=follow_symlinks, on_error=record_error
    ):
        key = str(found.path)
        seen.add(key)
        outcome.seen += 1
        current = existing.get(key)

        if current is None:
            digest = file_hash(found.path, hash_algorithm) if hash_files else None
            cursor = conn.execute(
                "INSERT INTO files"
                "(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
                " VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (key, _ext(found.path), found.size, found.mtime, digest, now, now),
            )
            outcome.new += 1
            outcome.changed_ids.append(cast(int, cursor.lastrowid))
            continue

        file_id, size, mtime, _is_missing = current
        if size == found.size and mtime == found.mtime:
            conn.execute(
                "UPDATE files SET last_seen = ?, is_missing = 0 WHERE id = ?", (now, file_id)
            )
            continue

        digest = file_hash(found.path, hash_algorithm) if hash_files else None
        conn.execute(
            """UPDATE files SET size = ?, mtime = ?, hash = ?, is_missing = 0, last_seen = ?
               WHERE id = ?""",
            (found.size, found.mtime, digest, now, file_id),
        )
        outcome.updated += 1
        outcome.changed_ids.append(file_id)

    for path, (file_id, _size, _mtime, is_missing) in existing.items():
        if path not in seen and not is_missing:
            conn.execute("UPDATE files SET is_missing = 1 WHERE id = ?", (file_id,))
            outcome.missing += 1

    conn.execute(
        """UPDATE scan_runs
           SET finished_at = ?, status = 'ok', files_seen = ?, files_new = ?,
               files_updated = ?, files_missing = ?, errors = ?
           WHERE id = ?""",
        (
            utcnow(),
            outcome.seen,
            outcome.new,
            outcome.updated,
            outcome.missing,
            outcome.error_count,
            run_id,
        ),
    )
    conn.commit()
    return outcome
