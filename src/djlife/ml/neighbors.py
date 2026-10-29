"""k-NN sobre embeddings: propoe genero para faixas ainda sem rotulo (L0/L1).

Referencias = faixas com embedding e rotulo (tags/rules). Alvos = faixas com
embedding e sem rotulo. Cada alvo recebe o genero da vizinhanca mais proxima,
gravado em `track_genres` com `source = "embedding"`, mantendo a proveniencia.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from djlife.ml import vectors
from djlife.ml.base import (
    CONFIDENCE_STRONG,
    CONFIDENCE_WEAK,
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_NEIGHBORS,
    GENRE_SOURCE,
    LABEL_SOURCES,
)
from djlife.scanner import utcnow

_INSERT = """
    INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(track_id, genre_id, source) DO NOTHING
"""


@dataclass(frozen=True)
class Proposal:
    file_id: int
    track_id: int
    genre_id: int
    genre: str
    score: float
    confidence: str
    neighbors: int


@dataclass(frozen=True)
class NeighborPlan:
    model: str
    model_version: str
    embedded: int
    labeled: int
    targets: int
    proposals: tuple[Proposal, ...]

    @property
    def pending(self) -> int:
        return len(self.proposals)


@dataclass(frozen=True)
class NeighborResult:
    written: int
    skipped: int


def build_plan(
    conn: sqlite3.Connection,
    model: str,
    model_version: str,
    *,
    k: int = DEFAULT_NEIGHBORS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    limit: int | None = None,
) -> NeighborPlan:
    """Calcula as propostas de genero ainda ausentes (dry-run)."""
    nested = ",".join("?" * len(LABEL_SOURCES))
    labels: dict[int, set[int]] = {}
    for row in conn.execute(
        f"SELECT t.file_id AS file_id, tg.genre_id AS genre_id FROM track_genres tg"
        f" JOIN tracks t ON t.id = tg.track_id WHERE tg.source IN ({nested})",
        LABEL_SOURCES,
    ):
        labels.setdefault(int(row["file_id"]), set()).add(int(row["genre_id"]))

    track_of = {
        int(row["file_id"]): int(row["id"])
        for row in conn.execute("SELECT id, file_id FROM tracks")
    }
    genre_slugs = {
        int(row["id"]): str(row["slug"]) for row in conn.execute("SELECT id, slug FROM genres")
    }
    existing = {
        (int(row["track_id"]), int(row["genre_id"]))
        for row in conn.execute(
            "SELECT track_id, genre_id FROM track_genres WHERE source = ?", (GENRE_SOURCE,)
        )
    }
    vectors_by_file = _load_vectors(conn, model, model_version)

    references = [(fid, vec) for fid, vec in vectors_by_file.items() if fid in labels]
    target_ids = sorted(fid for fid in vectors_by_file if fid not in labels)
    if limit is not None:
        target_ids = target_ids[:limit]

    proposals: list[Proposal] = []
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
            existing=existing,
        )
        if proposal is not None:
            proposals.append(proposal)

    return NeighborPlan(
        model=model,
        model_version=model_version,
        embedded=len(vectors_by_file),
        labeled=len(references),
        targets=len(target_ids),
        proposals=tuple(proposals),
    )


def apply_plan(conn: sqlite3.Connection, plan: NeighborPlan) -> NeighborResult:
    """Grava as propostas do plano em `track_genres` (nunca sobrescreve L0/L1)."""
    now = utcnow()
    written = 0
    skipped = 0
    for proposal in plan.proposals:
        cursor = conn.execute(
            _INSERT,
            (
                proposal.track_id,
                proposal.genre_id,
                GENRE_SOURCE,
                proposal.confidence,
                proposal.score,
                now,
            ),
        )
        written += cursor.rowcount
        skipped += 1 - cursor.rowcount
    conn.commit()
    return NeighborResult(written=written, skipped=skipped)


def _classify(
    file_id: int,
    track_id: int,
    vector: tuple[float, ...],
    references: list[tuple[int, tuple[float, ...]]],
    labels: dict[int, set[int]],
    genre_slugs: dict[int, str],
    *,
    k: int,
    min_similarity: float,
    existing: set[tuple[int, int]],
) -> Proposal | None:
    scored = sorted(
        (
            (vectors.cosine(vector, ref_vector), ref_id)
            for ref_id, ref_vector in references
            if len(ref_vector) == len(vector)
        ),
        reverse=True,
    )[:k]
    scored = [(score, ref_id) for score, ref_id in scored if score >= min_similarity]
    if not scored:
        return None

    votes: dict[int, float] = {}
    for score, ref_id in scored:
        for genre_id in labels[ref_id]:
            votes[genre_id] = votes.get(genre_id, 0.0) + score

    total = sum(votes.values())
    if total <= 0.0:
        return None
    genre_id = max(votes, key=lambda gid: (votes[gid], -gid))
    if (track_id, genre_id) in existing:
        return None

    agreement = votes[genre_id] / total
    confidence = (
        "A" if agreement >= CONFIDENCE_STRONG else "B" if agreement >= CONFIDENCE_WEAK else "C"
    )
    return Proposal(
        file_id=file_id,
        track_id=track_id,
        genre_id=genre_id,
        genre=genre_slugs.get(genre_id, str(genre_id)),
        score=agreement,
        confidence=confidence,
        neighbors=len(scored),
    )


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
