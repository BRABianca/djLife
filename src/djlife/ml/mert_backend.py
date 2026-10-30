"""Backend de embeddings com MERT (extra `ml`).

MERT (Music Understanding Model with Large-Scale Self-supervised Training, M-a-P) e um
modelo do tipo Wav2Vec2 treinado sobre audio musical. Roda em CPU e exige `torch` e o
download dos pesos na primeira execucao — por isso e um extra opcional e o modelo so e
carregado no primeiro `embed()` (o plano dry-run nao baixa nada). O vetor final e a media
das 13 camadas ocultas sobre os time-steps (768 dims).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from djlife.ml import vectors
from djlife.ml.base import EXTRA_HINT, Embedder, EmbeddingUnavailable
from djlife.scanner import extended

NAME = "mert"
MODEL_ID = "m-a-p/MERT-v1-95M"
MODEL_VERSION = "1"
DIM = 768
SAMPLE_RATE = 24000
DEFAULT_WINDOW_SECONDS = 30.0


def version_for(model_id: str | None = None) -> str:
    """`model_version` gravado em `embeddings` (sem tocar no modelo)."""
    return f"{model_id or MODEL_ID}@{MODEL_VERSION}"


def _librosa() -> Any:
    try:
        return importlib.import_module("librosa")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"librosa nao esta instalado. {EXTRA_HINT}") from exc


def _transformers() -> Any:
    try:
        return importlib.import_module("transformers")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"transformers nao esta instalado. {EXTRA_HINT}") from exc


def _torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise EmbeddingUnavailable(f"torch nao esta instalado. {EXTRA_HINT}") from exc


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


class MertEmbedder:
    name = NAME
    dim = DIM

    def __init__(self, *, model_id: str | None = None, window_seconds: float | None = None) -> None:
        self._model_id = model_id or MODEL_ID
        self.version = version_for(model_id)
        self._window_seconds = window_seconds
        self._processor: Any = None
        self._model: Any = None
        self._torch: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        transformers = _transformers()
        torch = _torch()
        processor = transformers.Wav2Vec2FeatureExtractor.from_pretrained(
            self._model_id, trust_remote_code=True
        )
        model = transformers.AutoModel.from_pretrained(self._model_id, trust_remote_code=True)
        model.eval()
        self._processor = processor
        self._model = model
        self._torch = torch

    def embed(self, path: Path) -> tuple[float, ...]:
        self._ensure_model()
        signal, sample_rate = _load_audio(_librosa(), path, self._window_seconds)
        if len(signal) == 0:
            raise ValueError(f"audio vazio: {path}")
        inputs = self._processor(signal, sampling_rate=sample_rate, return_tensors="pt")
        with self._torch.no_grad():
            outputs = self._model(**inputs, output_hidden_states=True)
        hidden = self._torch.stack(outputs.hidden_states)  # (camadas, lote, passos, dim)
        pooled = hidden.mean(dim=(0, 2))  # media sobre camadas e tempo -> (lote, dim)
        return vectors.l2_normalize([float(value) for value in pooled[0]])


def create(*, model_id: str | None = None, window_seconds: float | None = None) -> Embedder:
    """Instancia o backend, falhando cedo se o extra nao estiver instalado."""
    _transformers()
    _torch()
    _librosa()
    return MertEmbedder(model_id=model_id, window_seconds=window_seconds)
