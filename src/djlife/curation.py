"""Curadoria humana das faixas com genero incoerente entre as fontes.

Reune as classificacoes gravadas em ``track_genres`` e aponta os **conflitos entre fontes**
(tags L0 x regras L1 x embeddings L3). A fila e ordenada pelos casos mais graves; cada decisao
manual do usuario e gravada com ``source = 'manual'`` e passa a ser a classificacao primaria
(prioritaria em ``planner._primary``). Nada no filesystem e tocado aqui.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from djlife import planner
from djlife.scanner import utcnow

MANUAL_SOURCE = "manual"
MANUAL_CONFIDENCE = "A"

LEVEL_DIVERGENTE = "divergente"
LEVEL_AMBIGUA = "ambigua"

_SEPARATOR = " > "


@dataclass(frozen=True)
class Signal:
    """Uma classificacao gravada: qual fonte, com que confianca, para qual genero."""

    source: str
    confidence: str
    genre_id: int
    root: str
    leaf: str
    level: int

    @property
    def label(self) -> str:
        return f"{self.root}{_SEPARATOR}{self.leaf}" if self.leaf else self.root


@dataclass(frozen=True)
class Choice:
    genre_id: int
    label: str
    slug: str


@dataclass(frozen=True)
class ReviewItem:
    track_id: int
    file_id: int
    path: str
    title: str
    artist: str
    signals: tuple[Signal, ...]
    level: str

    @property
    def suggestion(self) -> Signal:
        """Sinal mais provavel, usado como palpite default na revisao."""
        return min(self.signals, key=_signal_key)

    @property
    def labels(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for signal in self.signals:
            bucket = grouped.setdefault(signal.source, [])
            if signal.label not in bucket:
                bucket.append(signal.label)
        return grouped


def _signal_key(signal: Signal) -> tuple[int, int, int, int]:
    return (
        planner.SOURCE_ORDER.get(signal.source, 9),
        planner.CONFIDENCE_ORDER.get(signal.confidence, 9),
        -signal.level,
        signal.genre_id,
    )


def _reviewed_tracks(conn: sqlite3.Connection) -> set[int]:
    return {
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT track_id FROM track_genres WHERE source = ?", (MANUAL_SOURCE,)
        )
    }


def _conflict_level(signals: list[Signal]) -> str | None:
    """Classifica o conflito ou devolve ``None`` quando as fontes concordam."""
    by_source: dict[str, set[str]] = {}
    for signal in signals:
        by_source.setdefault(signal.source, set()).add(signal.label)
    if len(by_source) < 2:
        return None
    labels = set().union(*by_source.values())
    if len(labels) < 2:
        return None
    roots = {label.split(_SEPARATOR)[0] for label in labels}
    return LEVEL_DIVERGENTE if len(roots) > 1 else LEVEL_AMBIGUA


def genre_choices(conn: sqlite3.Connection) -> list[Choice]:
    """Generos ativos com rotulo ``raiz > subgenero`` para o menu de revisao."""
    genres = planner.genre_index(conn)
    active = {int(row[0]) for row in conn.execute("SELECT id FROM genres WHERE is_active = 1")}
    choices: list[Choice] = []
    for genre_id in sorted(active):
        node = genres.get(genre_id)
        if node is None:
            continue
        root, leaf = planner.root_and_leaf(genres, genre_id)
        choices.append(Choice(genre_id, f"{root}{_SEPARATOR}{leaf}" if leaf else root, node.slug))
    choices.sort(key=lambda choice: choice.label.casefold())
    return choices


def build_queue(conn: sqlite3.Connection) -> list[ReviewItem]:
    """Faixas com conflito entre fontes e ainda sem decisao manual, mais graves primeiro."""
    genres = planner.genre_index(conn)
    reviewed = _reviewed_tracks(conn)
    sql = (
        "SELECT tg.track_id AS track_id, tg.genre_id AS genre_id, tg.confidence AS confidence,"
        " tg.source AS source, t.file_id AS file_id, t.title AS title, t.artist AS artist,"
        " f.path AS path"
        " FROM track_genres tg"
        " JOIN tracks t ON t.id = tg.track_id"
        " JOIN files f ON f.id = t.file_id"
        " WHERE f.is_missing = 0"
        " ORDER BY tg.track_id, tg.source, tg.genre_id"
    )
    signals: dict[int, list[Signal]] = {}
    meta: dict[int, tuple[int, str, str, str]] = {}
    for row in conn.execute(sql):
        track_id = int(row["track_id"])
        if track_id in reviewed:
            continue
        genre_id = int(row["genre_id"])
        node = genres.get(genre_id)
        if node is None:
            continue
        root, leaf = planner.root_and_leaf(genres, genre_id)
        signals.setdefault(track_id, []).append(
            Signal(str(row["source"]), str(row["confidence"]), genre_id, root, leaf, node.level)
        )
        meta.setdefault(
            track_id,
            (int(row["file_id"]), str(row["path"]), str(row["title"] or ""), str(row["artist"] or "")),
        )

    items: list[ReviewItem] = []
    for track_id, track_signals in signals.items():
        level = _conflict_level(track_signals)
        if level is None:
            continue
        file_id, path, title, artist = meta[track_id]
        items.append(
            ReviewItem(track_id, file_id, path, title, artist, tuple(track_signals), level)
        )
    items.sort(key=lambda item: (0 if item.level == LEVEL_DIVERGENTE else 1, item.path.casefold()))
    return items


def record_decision(conn: sqlite3.Connection, track_id: int, genre_id: int) -> None:
    """Grava a decisao manual (``source='manual'``) e a torna a classificacao primaria."""
    conn.execute(
        "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
        " VALUES (?, ?, ?, ?, NULL, ?)"
        " ON CONFLICT(track_id, genre_id, source) DO NOTHING",
        (track_id, genre_id, MANUAL_SOURCE, MANUAL_CONFIDENCE, utcnow()),
    )
    conn.commit()
