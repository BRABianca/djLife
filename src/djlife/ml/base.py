"""Contrato dos backends de embeddings (camada L3)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

EMBEDDERS: tuple[str, ...] = ("clap", "mert", "muq")

EXTRA_HINT = 'Instale o extra: pip install -e ".[ml]"'

# Fonte gravada em `track_genres`: propostas do k-NN nunca se misturam com L0/L1.
GENRE_SOURCE = "embedding"
LABEL_SOURCES: tuple[str, ...] = ("tags", "rules")

DEFAULT_NEIGHBORS = 10
DEFAULT_MIN_SIMILARITY = 0.6

# Faixas de confianca pelo peso da vizinhanca que concorda com o genero proposto.
CONFIDENCE_STRONG = 0.6
CONFIDENCE_WEAK = 0.4


class EmbeddingUnavailable(RuntimeError):
    """Backend de embeddings indisponivel no ambiente."""


class Embedder(Protocol):
    name: str
    version: str
    dim: int

    def embed(self, path: Path) -> tuple[float, ...]: ...
