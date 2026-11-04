"""Contrato dos backends de analise de audio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

BACKENDS: tuple[str, ...] = ("librosa", "essentia")

DEFAULT_FAST_SECONDS = 90.0

# `analysis_version` distingue a analise completa da "fast analysis" (primeiros N
# segundos), para que as duas possam coexistir em `audio_analysis`.
FULL_VERSION = "1"
FAST_VERSION = "fast-1"


class AnalysisUnavailable(RuntimeError):
    """Backend de analise de audio indisponivel no ambiente."""


@dataclass(frozen=True)
class TrackFeatures:
    bpm: float | None = None
    key_camelot: str | None = None
    key_open: str | None = None
    energy: float | None = None
    danceability: float | None = None
    loudness_lufs: float | None = None


class Analyzer(Protocol):
    name: str
    version: str

    def analyze(self, path: Path) -> TrackFeatures: ...
