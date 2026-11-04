"""Camada L3 do catalogo: embeddings de audio, k-NN de genero e aprendizado por correcoes.

Backend plugavel atraves de `load_embedder`: `clap` (extra `ml`, roda na CPU).
Os vetores ficam em `embeddings`; as propostas de genero saem em `track_genres`
com `source = "embedding"` (k-NN) ou `source = "learned"` (correcoes do usuario),
sem nunca sobrescrever as camadas L0/L1.
"""

from __future__ import annotations

from djlife.ml.base import EMBEDDERS, Embedder, EmbeddingUnavailable
from djlife.ml.learning import (
    LearnedProposal,
    LearnPlan,
    LearnResult,
    NeighborVote,
)
from djlife.ml.learning import (
    apply_plan as apply_learn_plan,
)
from djlife.ml.learning import (
    build_plan as build_learn_plan,
)
from djlife.ml.neighbors import (
    NeighborPlan,
    NeighborResult,
    Proposal,
)
from djlife.ml.neighbors import (
    apply_plan as apply_neighbor_plan,
)
from djlife.ml.neighbors import (
    build_plan as build_neighbor_plan,
)
from djlife.ml.runner import (
    Candidate,
    EmbedPlan,
    EmbedResult,
    apply_plan,
    build_plan,
    embedder_version,
    load_embedder,
)

__all__ = [
    "EMBEDDERS",
    "Candidate",
    "EmbedPlan",
    "EmbedResult",
    "Embedder",
    "EmbeddingUnavailable",
    "LearnPlan",
    "LearnResult",
    "LearnedProposal",
    "NeighborPlan",
    "NeighborResult",
    "NeighborVote",
    "Proposal",
    "apply_learn_plan",
    "apply_neighbor_plan",
    "apply_plan",
    "build_learn_plan",
    "build_neighbor_plan",
    "build_plan",
    "embedder_version",
    "load_embedder",
]
