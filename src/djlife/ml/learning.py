"""Aprendizado pelas correcoes do usuario (camada `learned`, k-NN sobre embeddings).

Referencias = faixas com embedding e **correcao humana** (``source='manual'``); alvos =
faixas com embedding e ainda sem correcao. Cada voto e ponderado por similaridade de
cosseno **e recencia** (decaimento temporal, para lidar com *concept drift*). O resultado
e gravado em ``track_genres`` com ``source='learned'`` e o ``model_version`` do indice de
embeddings, mantendo a proveniencia reproduzivel. Nenhum arquivo e movido aqui.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from djlife.ml import vectors
from djlife.ml.base import (
    CONFIDENCE_STRONG,
    CONFIDENCE_WEAK,
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_NEIGHBORS,
)
from djlife.scanner import utcnow

GENRE_SOURCE = "learned"
REFERENCE_SOURCE = "manual"

# Meia-vida do decaimento temporal dos votos: uma correcao de ~6 meses pesa metade.
DEFAULT_HALF_LIFE_DAYS = 180.0

_INSERT = """
    INSERT INTO track_genres(
        track_id, genre_id, source, confidence, score, model_version, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(track_id, genre_id, source) DO NOTHING
"""


@dataclass(frozen=True)
class NeighborVote:
    """Um vizinho que votou, com a similaridade e o peso efetivo (similaridade x recencia)."""

    file_id: int
    genre: str
    similarity: float
    weight: float


@dataclass(frozen=True)
class LearnedProposal:
    file_id: int
    track_id: int
    genre_id: int
    genre: str
    score: float
    confidence: str
    votes: tuple[NeighborVote, ...]


@dataclass(frozen=True)
class LearnPlan:
    model: str
    model_version: str
    embedded: int
    references: int
    targets: int
    proposals: tuple[LearnedProposal, ...]

    @property
    def pending(self) -> int:
        return len(self.proposals)


@dataclass(frozen=True)
class LearnResult:
    written: int
    removed: int


def build_plan(
    conn: sqlite3.Connection,
    model: str,
    model_version: str,
    *,
    k: int = DEFAULT_NEIGHBORS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    min_confidence: float = CONFIDENCE_WEAK,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    limit: int | None = None,
    now: datetime | None = None,
) -> LearnPlan:
    """Calcula as propostas da camada ``learned`` a partir das correcoes (dry-run)."""
    reference_time = now or datetime.now(UTC)
    labels, recency = _load_references(conn)
    genre_slugs = {
        int(row["id"]): str(row["slug"]) for row in conn.execute("SELECT id, slug FROM genres")
    }
    track_of = {
        int(row["file_id"]): int(row["id"])
        for row in conn.execute("SELECT id, file_id FROM tracks")
    }
    vectors_by_file = _load_vectors(conn, model, model_version)

    references = [
        (file_id, vector, recency.get(file_id, ""))
        for file_id, vector in vectors_by_file.items()
        if file_id in labels
    ]
    target_ids = sorted(file_id for file_id in vectors_by_file if file_id not in labels)
    if limit is not None:
        target_ids = target_ids[:limit]

    proposals: list[LearnedProposal] = []
    if references:
        for file_id in target_ids:
            track_id = track_of.get(file_id)
            if track_id is None:
                continue
            proposal = _classify(
                file_id,
                track_id,
                vectors_by_file[file_id],
                references,
                labels,
                genre_slugs,
                k=k,
                min_similarity=min_similarity,
                min_confidence=min_confidence,
                half_life_days=half_life_days,
                now=reference_time,
            )
            if proposal is not None:
                proposals.append(proposal)

    return LearnPlan(
        model=model,
        model_version=model_version,
        embedded=len(vectors_by_file),
        references=len(references),
        targets=len(target_ids),
        proposals=tuple(proposals),
    )


def apply_plan(conn: sqlite3.Connection, plan: LearnPlan) -> LearnResult:
    """Recalcula `learned`: remove o resultado anterior e grava as novas propostas."""
    removed = conn.execute("DELETE FROM track_genres WHERE source = ?", (GENRE_SOURCE,)).rowcount
    now = utcnow()
    written = 0
    for proposal in plan.proposals:
        cursor = conn.execute(
            _INSERT,
            (
                proposal.track_id,
                proposal.genre_id,
                GENRE_SOURCE,
                proposal.confidence,
                proposal.score,
                plan.model_version,
                now,
            ),
        )
        written += cursor.rowcount
    conn.commit()
    return LearnResult(written=written, removed=removed)


def _load_references(conn: sqlite3.Connection) -> tuple[dict[int, set[int]], dict[int, str]]:
    """Correcoes humanas por arquivo: generos escolhidos e a data da correcao mais recente."""
    labels: dict[int, set[int]] = {}
    recency: dict[int, str] = {}
    for row in conn.execute(
        "SELECT t.file_id AS file_id, tg.genre_id AS genre_id, tg.created_at AS created_at"
        " FROM track_genres tg JOIN tracks t ON t.id = tg.track_id WHERE tg.source = ?",
        (REFERENCE_SOURCE,),
    ):
        file_id = int(row["file_id"])
        labels.setdefault(file_id, set()).add(int(row["genre_id"]))
        created = str(row["created_at"])
        if file_id not in recency or created > recency[file_id]:
            recency[file_id] = created
    return labels, recency


def _classify(
    file_id: int,
    track_id: int,
    vector: tuple[float, ...],
    references: list[tuple[int, tuple[float, ...], str]],
    labels: dict[int, set[int]],
    genre_slugs: dict[int, str],
    *,
    k: int,
    min_similarity: float,
    min_confidence: float,
    half_life_days: float,
    now: datetime,
) -> LearnedProposal | None:
    scored = sorted(
        (
            (vectors.cosine(vector, ref_vector), ref_id, ref_created)
            for ref_id, ref_vector, ref_created in references
            if len(ref_vector) == len(vector)
        ),
        reverse=True,
    )[:k]
    scored = [item for item in scored if item[0] >= min_similarity]
    if not scored:
        return None

    votes: dict[int, float] = {}
    detail: list[tuple[float, int, float]] = []
    for similarity, ref_id, ref_created in scored:
        weight = similarity * _decay(ref_created, now=now, half_life_days=half_life_days)
        detail.append((similarity, ref_id, weight))
        for genre_id in labels[ref_id]:
            votes[genre_id] = votes.get(genre_id, 0.0) + weight

    total = sum(votes.values())
    if total <= 0.0:
        return None
    genre_id = max(votes, key=lambda gid: (votes[gid], -gid))
    agreement = votes[genre_id] / total
    if agreement < min_confidence:
        return None

    confidence = "A" if agreement >= CONFIDENCE_STRONG else "B"
    detail.sort(key=lambda item: item[2], reverse=True)
    neighbor_votes = tuple(
        NeighborVote(
            file_id=ref_id,
            genre=genre_slugs.get(voted_id, str(voted_id)),
            similarity=similarity,
            weight=weight,
        )
        for similarity, ref_id, weight in detail
        for voted_id in sorted(labels[ref_id])
    )
    return LearnedProposal(
        file_id=file_id,
        track_id=track_id,
        genre_id=genre_id,
        genre=genre_slugs.get(genre_id, str(genre_id)),
        score=agreement,
        confidence=confidence,
        votes=neighbor_votes,
    )


def _decay(created_at: str, *, now: datetime, half_life_days: float) -> float:
    """Peso por recencia: 1.0 no instante da correcao, 0.5 a cada meia-vida."""
    if half_life_days <= 0.0:
        return 1.0
    try:
        when = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return 1.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age_days = max((now - when).total_seconds() / 86400.0, 0.0)
    return float(0.5 ** (age_days / half_life_days))


def _load_vectors(
    conn: sqlite3.Connection, model: str, model_version: str
) -> dict[int, tuple[float, ...]]:
    return {
        int(row["file_id"]): vectors.unpack(row["vector"])
        for row in conn.execute(
            "SELECT e.file_id AS file_id, e.vector AS vector FROM embeddings e"
            " JOIN files f ON f.id = e.file_id"
            " WHERE f.is_missing = 0 AND e.model = ? AND e.model_version = ?",
            (model, model_version),
        )
    }
