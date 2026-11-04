"""Exportacao de playlists M3U8 a partir do catalogo.

Projeta as classificacoes do catalogo (fonte de verdade) em arquivos ``.m3u8`` agrupados por
genero e subgenero, sem tocar nos arquivos de audio. Complementa ``plan``/``apply`` como outra
forma de organizar a biblioteca no filesystem, util para players e softwares de DJ que leem
playlists por caminho.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from djlife.planner import DEFAULT_UNKNOWN_DIR, resolve_labels

GROUP_BY = ("genre", "subgenre")
EXTENSION = ".m3u8"


@dataclass(frozen=True)
class PlaylistTrack:
    path: Path
    title: str
    artist: str
    duration: float


@dataclass(frozen=True)
class Playlist:
    genre: str
    subgenre: str
    relative: Path
    tracks: tuple[PlaylistTrack, ...]


@dataclass(frozen=True)
class ExportPlan:
    out_dir: Path
    group_by: str
    playlists: tuple[Playlist, ...]

    @property
    def total(self) -> int:
        """Total de faixas distribuidas nas playlists."""
        return sum(len(playlist.tracks) for playlist in self.playlists)


@dataclass(frozen=True)
class ExportResult:
    out_dir: Path
    playlists: int
    tracks: int
    errors: int


def _relative(genre: str, subgenre: str, group_by: str) -> Path:
    if group_by == "genre":
        return Path(f"{genre}{EXTENSION}")
    return Path(genre) / f"{subgenre or genre}{EXTENSION}"


def build_plan(
    conn: sqlite3.Connection,
    *,
    out_dir: Path,
    group_by: str = "genre",
    unknown_dir: str = DEFAULT_UNKNOWN_DIR,
) -> ExportPlan:
    """Agrupa as faixas classificadas em playlists por genero (ou subgenero)."""
    if group_by not in GROUP_BY:
        raise ValueError(f"group_by invalido: {group_by!r}. Use um de {', '.join(GROUP_BY)}.")

    labels = resolve_labels(conn)
    buckets: dict[tuple[str, str], list[PlaylistTrack]] = {}
    sql = (
        "SELECT t.id AS track_id, t.title, t.artist, t.duration, f.path AS path"
        " FROM tracks t JOIN files f ON f.id = t.file_id"
        " WHERE f.is_missing = 0 ORDER BY f.path"
    )
    for row in conn.execute(sql):
        label = labels.get(int(row["track_id"]))
        if label is None or not label[0]:
            genre, subgenre = unknown_dir, ""
        else:
            genre, subgenre = label
        key = (genre, "") if group_by == "genre" else (genre, subgenre)
        buckets.setdefault(key, []).append(
            PlaylistTrack(
                path=Path(str(row["path"])),
                title=str(row["title"] or ""),
                artist=str(row["artist"] or ""),
                duration=float(row["duration"] or 0.0),
            )
        )

    playlists = tuple(
        Playlist(
            genre=genre,
            subgenre=subgenre,
            relative=_relative(genre, subgenre, group_by),
            tracks=tuple(tracks),
        )
        for (genre, subgenre), tracks in sorted(buckets.items())
    )
    return ExportPlan(out_dir=Path(out_dir), group_by=group_by, playlists=playlists)


def _render(playlist: Playlist, base_dir: Path) -> str:
    lines = ["#EXTM3U"]
    for track in playlist.tracks:
        label = " - ".join(part for part in (track.artist, track.title) if part)
        lines.append(f"#EXTINF:{int(round(track.duration))},{label}")
        lines.append(_track_path(track.path, base_dir))
    return "\n".join(lines) + "\n"


def _track_path(path: Path, base_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path, base_dir)).as_posix()
    except ValueError:
        return path.as_posix()


def write(plan: ExportPlan) -> ExportResult:
    """Grava as playlists em ``plan.out_dir`` (UTF-8) e devolve o resumo."""
    written = 0
    tracks = 0
    errors = 0
    for playlist in plan.playlists:
        destination = plan.out_dir / playlist.relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(_render(playlist, destination.parent), encoding="utf-8")
        except OSError:
            errors += 1
            continue
        written += 1
        tracks += len(playlist.tracks)
    return ExportResult(out_dir=plan.out_dir, playlists=written, tracks=tracks, errors=errors)
