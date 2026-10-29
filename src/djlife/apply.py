from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from mutagen import MutagenError

from djlife import tags
from djlife.planner import STATUS_CONFLICT, STATUS_READY, STATUS_UNCLASSIFIED, Plan, PlanItem
from djlife.scanner import extended, utcnow

DJLIFE_KEYS = ("DJLIFE_GENRE", "DJLIFE_SUBGENRE", "DJLIFE_TAXONOMY_VERSION")
DEFAULT_TAXONOMY_VERSION = "0.0.0"


@dataclass(frozen=True)
class ApplyResult:
    batch: str
    strategy: str
    linked: int = 0
    moved: int = 0
    tagged: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def applied(self) -> int:
        return self.linked + self.moved + self.tagged


@dataclass(frozen=True)
class UndoResult:
    batch: str | None
    removed: int = 0
    restored: int = 0
    untagged: int = 0
    errors: int = 0


@dataclass(frozen=True)
class _Journal:
    conn: sqlite3.Connection
    batch: str
    now: str
    strategy: str

    def record(self, op: str, src: Path, dst: Path | None, file_id: int | None) -> None:
        self.conn.execute(
            "INSERT INTO journal(batch, created_at, op, strategy, src, dst, file_id, undone)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (self.batch, self.now, op, self.strategy, str(src), str(dst) if dst else None, file_id),
        )


def _tag_values(item: PlanItem, taxonomy_version: str) -> dict[str, str]:
    values = {"DJLIFE_TAXONOMY_VERSION": taxonomy_version}
    if item.genre:
        values["DJLIFE_GENRE"] = item.genre
    if item.subgenre:
        values["DJLIFE_SUBGENRE"] = item.subgenre
    return values


def taxonomy_version(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'taxonomy_version'").fetchone()
    return str(row["value"]) if row else DEFAULT_TAXONOMY_VERSION


def _record_error(conn: sqlite3.Connection, path: Path, stage: str, exc: Exception) -> None:
    conn.execute(
        "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
        (str(path), f"{stage}: {exc}"),
    )


def apply(
    conn: sqlite3.Connection,
    plan: Plan,
    *,
    write_tags: bool = True,
    batch: str | None = None,
) -> ApplyResult:
    batch = batch or uuid4().hex[:12]
    journal = _Journal(conn, batch, utcnow(), plan.strategy)
    version = taxonomy_version(conn)
    counters = {"linked": 0, "moved": 0, "tagged": 0, "skipped": 0, "errors": 0}

    for item in plan.items:
        if item.status != STATUS_READY:
            if item.status in (STATUS_CONFLICT, STATUS_UNCLASSIFIED):
                counters["skipped"] += 1
            continue

        destination: Path | None = item.dst
        try:
            if plan.strategy == "hardlink":
                assert destination is not None
                os.makedirs(extended(destination.parent), exist_ok=True)
                os.link(extended(item.src), extended(destination))
                journal.record("hardlink", item.src, destination, item.file_id)
                counters["linked"] += 1
            elif plan.strategy == "move":
                assert destination is not None
                os.makedirs(extended(destination.parent), exist_ok=True)
                shutil.move(extended(item.src), extended(destination))
                conn.execute(
                    "UPDATE files SET path = ? WHERE id = ?", (str(destination), item.file_id)
                )
                journal.record("move", item.src, destination, item.file_id)
                counters["moved"] += 1
            else:
                destination = item.src

            if write_tags:
                tags.write_tags(destination, _tag_values(item, version))
                journal.record("tag", destination, None, item.file_id)
                counters["tagged"] += 1
        except (OSError, MutagenError) as exc:
            counters["errors"] += 1
            _record_error(conn, destination or item.src, "apply", exc)
    conn.commit()

    return ApplyResult(
        batch=batch,
        strategy=plan.strategy,
        linked=counters["linked"],
        moved=counters["moved"],
        tagged=counters["tagged"],
        skipped=counters["skipped"],
        errors=counters["errors"],
    )


def last_batch(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT batch FROM journal WHERE undone = 0 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return str(row["batch"]) if row else None


def _prune_empty(directory: Path, stop: Path | None) -> None:
    current = directory
    limit = Path(stop) if stop is not None else None
    while True:
        if limit is not None and current == limit:
            return
        try:
            with os.scandir(extended(current)) as entries:
                if any(True for _ in entries):
                    return
        except OSError:
            return
        parent = current.parent
        if parent == current:
            return
        try:
            os.rmdir(extended(current))
        except OSError:
            return
        current = parent


def undo(
    conn: sqlite3.Connection,
    batch: str | None = None,
    *,
    stop: Path | None = None,
    quarantine_dir: Path | None = None,
) -> UndoResult:
    target_batch = batch or last_batch(conn)
    if target_batch is None:
        return UndoResult(batch=None)

    rows = list(
        conn.execute(
            "SELECT * FROM journal WHERE batch = ? AND undone = 0 ORDER BY id DESC",
            (target_batch,),
        )
    )
    counters = {"removed": 0, "restored": 0, "untagged": 0, "errors": 0}

    for row in rows:
        op = str(row["op"])
        src = Path(str(row["src"]))
        destination = Path(str(row["dst"])) if row["dst"] else None
        limit = quarantine_dir if row["strategy"] == "quarantine" else stop
        try:
            if op == "hardlink" and destination is not None:
                if destination.exists():
                    os.remove(extended(destination))
                    _prune_empty(destination.parent, limit)
                    counters["removed"] += 1
            elif op == "move" and destination is not None:
                if destination.exists():
                    os.makedirs(extended(src.parent), exist_ok=True)
                    shutil.move(extended(destination), extended(src))
                    conn.execute(
                        "UPDATE files SET path = ? WHERE id = ?", (str(src), row["file_id"])
                    )
                    _prune_empty(destination.parent, limit)
                    counters["restored"] += 1
            elif op == "tag" and src.exists() and tags.remove_tags(src, DJLIFE_KEYS):
                counters["untagged"] += 1
            conn.execute("UPDATE journal SET undone = 1 WHERE id = ?", (row["id"],))
        except (OSError, MutagenError) as exc:
            counters["errors"] += 1
            _record_error(conn, destination or src, "undo", exc)
    conn.commit()

    return UndoResult(
        batch=target_batch,
        removed=counters["removed"],
        restored=counters["restored"],
        untagged=counters["untagged"],
        errors=counters["errors"],
    )
