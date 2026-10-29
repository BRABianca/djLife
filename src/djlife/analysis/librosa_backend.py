"""Backend de analise de audio com librosa (roda nativo no Windows).

Extrai BPM (via `beat_track`) e tonalidade (croma + perfis de Krumhansl-Kessler),
entregando as notacoes Camelot e Open Key. Dependencia opcional: extra `analysis`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from djlife.analysis import camelot
from djlife.analysis.base import (
    DEFAULT_FAST_SECONDS,
    FAST_VERSION,
    FULL_VERSION,
    AnalysisUnavailable,
    Analyzer,
    TrackFeatures,
)
from djlife.scanner import extended

NAME = "librosa"
EXTRA_HINT = 'Instale o extra: pip install -e ".[analysis]"'
SAMPLE_RATE = 22050
BPM_RANGE = (70.0, 180.0)

# Perfis de Krumhansl-Kessler, indexados pela tonica.
_MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _librosa() -> Any:
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise AnalysisUnavailable(f"librosa nao esta instalado. {EXTRA_HINT}") from exc
    return librosa


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise AnalysisUnavailable(f"numpy nao esta instalado. {EXTRA_HINT}") from exc
    return numpy


def _load_audio(librosa: Any, path: Path, max_seconds: float | None) -> tuple[Any, int]:
    raw = str(path)
    try:
        signal, sample_rate = librosa.load(raw, sr=SAMPLE_RATE, mono=True, duration=max_seconds)
    except (OSError, RuntimeError):
        if raw.startswith("\\\\?\\"):
            raise
        signal, sample_rate = librosa.load(
            extended(raw), sr=SAMPLE_RATE, mono=True, duration=max_seconds
        )
    return signal, int(sample_rate)


def _estimate_bpm(numpy: Any, librosa: Any, signal: Any, sample_rate: int) -> float | None:
    tempo, _ = librosa.beat.beat_track(y=signal, sr=sample_rate)
    values = numpy.atleast_1d(numpy.asarray(tempo, dtype=float)).reshape(-1)
    if values.size == 0:
        return None
    bpm = float(values[0])
    if bpm <= 0:
        return None
    low, high = BPM_RANGE
    while bpm < low:
        bpm *= 2
    while bpm > high:
        bpm /= 2
    return round(bpm, 2)


def _estimate_key(numpy: Any, chroma: Any) -> tuple[int, str] | None:
    profile = numpy.asarray(chroma, dtype=float).mean(axis=1)
    if not bool(numpy.isfinite(profile).all()) or float(profile.max()) <= 0.0:
        return None

    major = numpy.asarray(_MAJOR_PROFILE, dtype=float)
    minor = numpy.asarray(_MINOR_PROFILE, dtype=float)
    best_score = float("-inf")
    best: tuple[int, str] | None = None
    for pitch_class in range(12):
        for mode, table in ((camelot.MAJOR, major), (camelot.MINOR, minor)):
            score = float(numpy.corrcoef(profile, numpy.roll(table, pitch_class))[0, 1])
            if math.isfinite(score) and score > best_score:
                best_score = score
                best = (pitch_class, mode)
    return best


class LibrosaAnalyzer:
    name = NAME

    def __init__(self, *, fast: bool = False, fast_seconds: float = DEFAULT_FAST_SECONDS) -> None:
        self.version = FAST_VERSION if fast else FULL_VERSION
        self._max_seconds = fast_seconds if fast else None

    def analyze(self, path: Path) -> TrackFeatures:
        librosa = _librosa()
        numpy = _numpy()
        signal, sample_rate = _load_audio(librosa, path, self._max_seconds)
        if numpy.size(signal) == 0:
            raise ValueError(f"audio vazio: {path}")

        bpm = _estimate_bpm(numpy, librosa, signal, sample_rate)
        chroma = librosa.feature.chroma_cqt(y=signal, sr=sample_rate)
        key = _estimate_key(numpy, chroma)
        if key is None:
            return TrackFeatures(bpm=bpm)
        camelot_code, open_code = camelot.notations(*key)
        return TrackFeatures(bpm=bpm, key_camelot=camelot_code, key_open=open_code)


def create(*, fast: bool = False, fast_seconds: float = DEFAULT_FAST_SECONDS) -> Analyzer:
    """Instancia o backend, falhando cedo se o extra nao estiver instalado."""
    _librosa()
    _numpy()
    return LibrosaAnalyzer(fast=fast, fast_seconds=fast_seconds)
