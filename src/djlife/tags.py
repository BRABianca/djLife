from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4Tags

from djlife.scanner import extended, utcnow

CHUNK = 500


@dataclass(frozen=True)
class TagData:
    namespace: str
    entries: tuple[tuple[str, str], ...]
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None


def _text(frame: object) -> str:
    return str(frame)


def _id3(tags: Any) -> tuple[list[tuple[str, str]], dict[str, str]]:
    entries: list[tuple[str, str]] = []
    summary: dict[str, str] = {}
    for frame in tags.values():
        frame_id = getattr(frame, "FrameID", "")
        if frame_id == "TXXX":
            key = f"TXXX:{getattr(frame, 'desc', '')}"
            value = _text(frame)
        elif frame_id == "UFID":
            key = f"UFID:{getattr(frame, 'owner', '')}"
            value = bytes(getattr(frame, "data", b"")).decode("utf-8", "replace")
        elif frame_id[:1] in {"T", "W"}:
            key = frame_id
            value = _text(frame)
        elif frame_id == "COMM":
            key = f"COMM:{getattr(frame, 'desc', '')}"
            value = _text(frame)
        else:
            continue
        entries.append((key, value))
        if frame_id == "TIT2":
            summary["title"] = value
        elif frame_id == "TPE1":
            summary["artist"] = value
        elif frame_id == "TALB":
            summary["album"] = value
    return entries, summary


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, tuple):
        return "/".join(str(item) for item in value)
    return str(value)


def _mp4(tags: Any) -> tuple[list[tuple[str, str]], dict[str, str]]:
    entries: list[tuple[str, str]] = []
    summary: dict[str, str] = {}
    for key, value in tags.items():
        values = value if isinstance(value, list) else [value]
        text = "; ".join(_decode(item) for item in values)
        entries.append((key, text))
        if key == "\xa9nam":
            summary["title"] = text
        elif key == "\xa9ART":
            summary["artist"] = text
        elif key == "\xa9alb":
            summary["album"] = text
    return entries, summary


def _vorbis(tags: Mapping[str, Any]) -> tuple[list[tuple[str, str]], dict[str, str]]:
    entries: list[tuple[str, str]] = []
    summary: dict[str, str] = {}
    for key, value in tags.items():
        values = value if isinstance(value, list) else [value]
        text = "; ".join(str(item) for item in values)
        entries.append((str(key), text))
        lowered = str(key).lower()
        if lowered in {"title", "artist", "album"}:
            summary[lowered] = text
    return entries, summary


def _type_name(audio: object) -> str:
    return type(audio).__name__.lower()


def read_tags(path: Path) -> TagData:
    audio = MutagenFile(extended(path))
    if audio is None:
        return TagData(namespace="", entries=())

    namespace = _type_name(audio)
    tags = getattr(audio, "tags", None)
    if tags is None:
        entries: list[tuple[str, str]] = []
        summary: dict[str, str] = {}
    elif isinstance(tags, ID3):
        namespace = "id3"
        entries, summary = _id3(tags)
    elif isinstance(tags, MP4Tags):
        namespace = "mp4"
        entries, summary = _mp4(tags)
    else:
        namespace = "vorbis"
        entries, summary = _vorbis(tags)

    info = getattr(audio, "info", None)
    duration = float(info.length) if info is not None else None

    return TagData(
        namespace=namespace,
        entries=tuple(entries),
        title=summary.get("title"),
        artist=summary.get("artist"),
        album=summary.get("album"),
        duration=duration,
    )


def _ensure_tags(audio: Any) -> Any:
    tags = getattr(audio, "tags", None)
    if tags is None:
        audio.add_tags()
        tags = audio.tags
    return tags


def write_tags(path: Path, mapping: Mapping[str, str]) -> None:
    audio = MutagenFile(extended(path))
    if audio is None:
        raise MutagenError(f"Formato nao suportado: {path}")
    store = _ensure_tags(audio)
    if isinstance(store, ID3):
        id3: Any = store
        frame: Any = TXXX
        for key, value in mapping.items():
            id3.setall(f"TXXX:{key}", [frame(encoding=3, desc=key, text=value)])
    elif isinstance(store, MP4Tags):
        mp4: Any = store
        for key, value in mapping.items():
            mp4[f"----:com.apple.iTunes:{key}"] = [value.encode("utf-8")]
    else:
        vorbis: Any = store
        for key, value in mapping.items():
            vorbis[key] = [value]
    audio.save()


def remove_tags(path: Path, keys: Iterable[str]) -> bool:
    audio = MutagenFile(extended(path))
    if audio is None or getattr(audio, "tags", None) is None:
        return False
    store = audio.tags
    changed = False
    if isinstance(store, ID3):
        id3: Any = store
        for key in keys:
            frame_id = f"TXXX:{key}"
            if frame_id in id3:
                del id3[frame_id]
                changed = True
    elif isinstance(store, MP4Tags):
        mp4: Any = store
        for key in keys:
            freeform = f"----:com.apple.iTunes:{key}"
            if freeform in mp4:
                del mp4[freeform]
                changed = True
    else:
        vorbis: Any = store
        for key in keys:
            if key in vorbis:
                del vorbis[key]
                changed = True
    if changed:
        audio.save()
    return changed


def _store(conn: sqlite3.Connection, file_id: int, data: TagData, now: str) -> None:
    conn.execute("DELETE FROM tags WHERE file_id = ?", (file_id,))
    unique = dict(data.entries)
    conn.executemany(
        "INSERT INTO tags(file_id, namespace, key, value) VALUES (?, ?, ?, ?)",
        [(file_id, data.namespace, key, value) for key, value in unique.items()],
    )

    row = conn.execute("SELECT id FROM tracks WHERE file_id = ?", (file_id,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO tracks(file_id, title, artist, album, duration, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, data.title, data.artist, data.album, data.duration, now),
        )
    else:
        conn.execute(
            "UPDATE tracks SET title = ?, artist = ?, album = ?, duration = ? WHERE id = ?",
            (data.title, data.artist, data.album, data.duration, row["id"]),
        )


def _iter_file_rows(conn: sqlite3.Connection, file_ids: list[int] | None) -> Iterator[sqlite3.Row]:
    if file_ids is None:
        yield from conn.execute("SELECT id, path FROM files WHERE is_missing = 0")
        return
    for start in range(0, len(file_ids), CHUNK):
        batch = file_ids[start : start + CHUNK]
        placeholders = ",".join("?" * len(batch))
        yield from conn.execute(f"SELECT id, path FROM files WHERE id IN ({placeholders})", batch)


def index_tags(conn: sqlite3.Connection, file_ids: list[int] | None = None) -> tuple[int, int]:
    now = utcnow()
    indexed = 0
    errors = 0
    for row in _iter_file_rows(conn, file_ids):
        try:
            data = read_tags(Path(row["path"]))
        except (MutagenError, OSError, ValueError) as exc:
            errors += 1
            conn.execute(
                "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
                (row["path"], str(exc)),
            )
            continue
        _store(conn, row["id"], data, now)
        indexed += 1
    conn.commit()
    return indexed, errors
