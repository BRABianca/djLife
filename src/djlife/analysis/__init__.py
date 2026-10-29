"""Analise de audio do catalogo: BPM e tonalidade (Camelot/Open Key).

Backends plugaveis atraves de `load_analyzer`: `librosa` (roda nativo no Windows)
e `essentia` (extra opcional, sem wheel Windows).
"""

from __future__ import annotations

from djlife.analysis.base import (
    BACKENDS,
    DEFAULT_FAST_SECONDS,
    AnalysisUnavailable,
    Analyzer,
    TrackFeatures,
)
from djlife.analysis.runner import (
    AnalyzePlan,
    AnalyzeResult,
    Candidate,
    apply_plan,
    build_plan,
    load_analyzer,
)

__all__ = [
    "BACKENDS",
    "DEFAULT_FAST_SECONDS",
    "AnalysisUnavailable",
    "AnalyzePlan",
    "AnalyzeResult",
    "Analyzer",
    "Candidate",
    "TrackFeatures",
    "apply_plan",
    "build_plan",
    "load_analyzer",
]
