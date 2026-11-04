from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from djlife.scanner import extended, utcnow

STRATEGY = "quarantine"


@dataclass(frozen=True)
class QuarantineItem:
    file_id: int
    src: Path
    dst: Path
    kind: str
    keeper: str
    size: int


@dataclass(frozen=True)
class QuarantinePlan:
    quarantine_dir: Path
    items: tuple[QuarantineItem, ...]

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def bytes_reclaimable(self) -> int:
        return sum(item.size for item in self.items)


@dataclass(frozen=True)
class QuarantineResult:
    batch: str
    moved: int = 0
    errors: int = 0


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _under(path: Path, root: Path) -> bool:
    normalized = _norm(path)
    prefix = _norm(root).rstrip(os.sep) + os.sep
    return normalized.startswith(prefix)


def _unique(path: Path, taken: set[str]) -> Path:
    candidate = path
    index = 2
    while _norm(candidate) in taken or candidate.exists():
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        index += 1
    taken.add(_norm(candidate))
    return candidate


def build_quarantine_plan(conn: sqlite3.Connection, quarantine_dir: Path) -> QuarantinePlan:
    root = Path(quarantine_dir)
    taken: set[str] = set()
    seen: set[int] = set()
    items: list[QuarantineItem] = []

    rows = conn.execute(
        "SELECT m.file_id, m.group_id, g.kind, f.path, f.size, f.is_missing"
        " FROM dup_members m"
        " JOIN dup_groups g ON g.id = m.group_id"
        " JOIN files f ON f.id = m.file_id"
        " WHERE m.is_keeper = 0 AND f.is_missing = 0"
        " ORDER BY f.path"
    )
    for row in rows:
        file_id = int(row["file_id"])
        if file_id in seen:
            continue
        src = Path(str(row["path"]))
        if _under(src, root):
            continue
        keeper_row = conn.execute(
            "SELECT f.path FROM dup_members m JOIN files f ON f.id = m.file_id"
            " WHERE m.group_id = ? AND m.is_keeper = 1",
            (row["group_id"],),
        ).fetchone()
        keeper = str(keeper_row["path"]) if keeper_row else ""
        seen.add(file_id)
        items.append(
            QuarantineItem(
                file_id=file_id,
                src=src,
                dst=_unique(root / str(row["kind"]) / src.name, taken),
                kind=str(row["kind"]),
                keeper=keeper,
                size=int(row["size"]),
            )
        )
    return QuarantinePlan(quarantine_dir=root, items=tuple(items))


def apply_quarantine(
    conn: sqlite3.Connection, plan: QuarantinePlan, *, batch: str | None = None
) -> QuarantineResult:
    batch = batch or uuid4().hex[:12]
    now = utcnow()
    moved = 0
    errors = 0
    for item in plan.items:
        try:
            os.makedirs(extended(item.dst.parent), exist_ok=True)
            shutil.move(extended(item.src), extended(item.dst))
            conn.execute("UPDATE files SET path = ? WHERE id = ?", (str(item.dst), item.file_id))
            conn.execute(
                "INSERT INTO journal(batch, created_at, op, strategy, src, dst, file_id, undone)"
                " VALUES (?, ?, 'move', ?, ?, ?, ?, 0)",
                (batch, now, STRATEGY, str(item.src), str(item.dst), item.file_id),
            )
            moved += 1
        except OSError as exc:
            errors += 1
            conn.execute(
                "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
                (str(item.src), f"quarantine: {exc}"),
            )
    conn.commit()
    return QuarantineResult(batch=batch, moved=moved, errors=errors)
