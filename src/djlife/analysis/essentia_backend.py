"""Backend de analise com Essentia (AGPL-3.0), exposto como extra opcional.

O Essentia nao publica wheel para Windows: o extra `essentia` so instala em
Linux/WSL2/Docker. Sem ele, o comando degrada para `AnalysisUnavailable`.
"""

from __future__ import annotations

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

NAME = "essentia"
EXTRA_HINT = 'Instale o extra (Linux/WSL2/Docker): pip install -e ".[essentia]"'
SAMPLE_RATE = 44100

_PITCH_CLASSES: dict[str, int] = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def _essentia() -> Any:
    try:
        import essentia.standard as es  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise AnalysisUnavailable(f"essentia nao esta instalado. {EXTRA_HINT}") from exc
    return es


class EssentiaAnalyzer:
    name = NAME

    def __init__(self, *, fast: bool = False, fast_seconds: float = DEFAULT_FAST_SECONDS) -> None:
        self.version = FAST_VERSION if fast else FULL_VERSION
        self._max_seconds = fast_seconds if fast else None

    def analyze(self, path: Path) -> TrackFeatures:
        es = _essentia()
        signal = es.MonoLoader(filename=str(path), sampleRate=SAMPLE_RATE)()
        if self._max_seconds is not None:
            signal = signal[: int(SAMPLE_RATE * self._max_seconds)]
        if len(signal) == 0:
            raise ValueError(f"audio vazio: {path}")

        bpm, *_ = es.RhythmExtractor2013()(signal)
        danceability, _ = es.Danceability()(signal)
        key, scale, _strength = es.KeyExtractor()(signal)
        camelot_code, open_code = _notations(key, scale)
        return TrackFeatures(
            bpm=round(float(bpm), 2),
            key_camelot=camelot_code,
            key_open=open_code,
            danceability=round(float(danceability), 4),
        )


def _notations(key: str, scale: str) -> tuple[str | None, str | None]:
    pitch_class = _PITCH_CLASSES.get(key)
    if pitch_class is None:
        return None, None
    mode = camelot.MINOR if scale == camelot.MINOR else camelot.MAJOR
    return camelot.notations(pitch_class, mode)


def create(*, fast: bool = False, fast_seconds: float = DEFAULT_FAST_SECONDS) -> Analyzer:
    """Instancia o backend, falhando cedo se o extra nao estiver instalado."""
    _essentia()
    return EssentiaAnalyzer(fast=fast, fast_seconds=fast_seconds)
