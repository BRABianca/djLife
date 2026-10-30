"""Backend de embeddings com MuQ (extra `muq`).

MuQ (Music Query) e um modelo musical auto-supervisionado (`OpenMuQ/MuQ-large-msd-iter`,
~300M parametros, 1024 dims) distribuido pelo pacote `muq`. Roda em CPU e baixa os pesos
na primeira execucao — o modelo so e carregado no primeiro `embed()`, de modo que o plano
dry-run nao baixa nada.

Obs.: o codigo e MIT, mas os pesos sao CC-BY-NC 4.0 (uso nao comercial).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from djlife.ml import vectors
from djlife.ml.base import Embedder, EmbeddingUnavailable
from djlife.scanner import extended

NAME = "muq"
MODEL_ID = "OpenMuQ/MuQ-large-msd-iter"
MODEL_VERSION = "1"
DIM = 1024
SAMPLE_RATE = 24000
DEFAULT_WINDOW_SECONDS = 30.0

_HINT = 'Instale o extra: pip install -e ".[muq]"'


def version_for(model_id: str | None = None) -> str:
    """`model_version` gravado em `embeddings` (sem tocar no modelo)."""
    return f"{model_id or MODEL_ID}@{MODEL_VERSION}"


def _librosa() -> Any:
    try:
        return importlib.import_module("librosa")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"librosa nao esta instalado. {_HINT}") from exc


def _torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"torch nao esta instalado. {_HINT}") from exc


def _muq() -> Any:
    try:
        return importlib.import_module("muq")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"muq nao esta instalado. {_HINT}") from exc


def _load_audio(librosa: Any, path: Path, seconds: float | None) -> tuple[Any, int]:
    raw = str(path)
    try:
        signal, sample_rate = librosa.load(raw, sr=SAMPLE_RATE, mono=True, duration=seconds)
    except (OSError, RuntimeError):
        if raw.startswith("\\\\?\\"):
            raise
        signal, sample_rate = librosa.load(
            extended(raw), sr=SAMPLE_RATE, mono=True, duration=seconds
        )
    return signal, int(sample_rate)


class MuqEmbedder:
    name = NAME
    dim = DIM

    def __init__(self, *, model_id: str | None = None, window_seconds: float | None = None) -> None:
        self._model_id = model_id or MODEL_ID
        self.version = version_for(model_id)
        self._window_seconds = window_seconds
        self._model: Any = None
        self._torch: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        torch = _torch()
        muq = _muq()
        model = muq.MuQ.from_pretrained(self._model_id)
        model.eval()
        self._model = model
        self._torch = torch

    def embed(self, path: Path) -> tuple[float, ...]:
        self._ensure_model()
        signal, sample_rate = _load_audio(_librosa(), path, self._window_seconds)
        if len(signal) == 0:
            raise ValueError(f"audio vazio: {path}")
        wavs = self._torch.from_numpy(signal).unsqueeze(0).to(self._torch.float32)
        with self._torch.no_grad():
            output = self._model(wavs, output_hidden_states=True)
        hidden = output.last_hidden_state  # (lote, passos, dim)
        pooled = hidden.mean(dim=1)  # media sobre o tempo -> (lote, dim)
        return vectors.l2_normalize([float(value) for value in pooled[0]])


def create(*, model_id: str | None = None, window_seconds: float | None = None) -> Embedder:
    """Instancia o backend, falhando cedo se o extra nao estiver instalado."""
    _muq()
    _torch()
    _librosa()
    return MuqEmbedder(model_id=model_id, window_seconds=window_seconds)
