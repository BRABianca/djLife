"""Orquestra a analise de audio sobre o catalogo (`audio_analysis`)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from djlife.analysis import essentia_backend, librosa_backend
from djlife.analysis.base import (
    BACKENDS,
    DEFAULT_FAST_SECONDS,
    Analyzer,
    TrackFeatures,
)
from djlife.scanner import utcnow

ProgressCallback = Callable[[int, int, str], None]

_INSERT = """
    INSERT INTO audio_analysis(
        file_id, analyzer, analysis_version, bpm, key_camelot, key_open,
        energy, danceability, loudness_lufs, analyzed_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(file_id, analyzer, analysis_version) DO UPDATE SET
        bpm = excluded.bpm,
        key_camelot = excluded.key_camelot,
        key_open = excluded.key_open,
        energy = excluded.energy,
        danceability = excluded.danceability,
        loudness_lufs = excluded.loudness_lufs,
        analyzed_at = excluded.analyzed_at
"""


def load_analyzer(
    name: str,
    *,
    fast: bool = False,
    fast_seconds: float = DEFAULT_FAST_SECONDS,
) -> Analyzer:
    """Instancia o backend pedido, sinalizando cedo se o extra nao estiver presente."""
    if name == librosa_backend.NAME:
        return librosa_backend.create(fast=fast, fast_seconds=fast_seconds)
    if name == essentia_backend.NAME:
        return essentia_backend.create(fast=fast, fast_seconds=fast_seconds)
    raise ValueError(f"backend invalido: {name!r}. Use um de {', '.join(BACKENDS)}.")


@dataclass(frozen=True)
class Candidate:
    file_id: int
    path: str


@dataclass(frozen=True)
class AnalyzePlan:
    analyzer: str
    version: str
    files: int
    analyzed: int
    candidates: tuple[Candidate, ...]

    @property
    def pending(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class AnalyzeResult:
    analyzer: str
    version: str
    analyzed: int
    failed: int
    errors: tuple[tuple[str, str], ...]


def build_plan(
    conn: sqlite3.Connection,
    analyzer: Analyzer,
    *,
    limit: int | None = None,
    force: bool = False,
) -> AnalyzePlan:
    """Seleciona os arquivos pendentes de analise para o backend (dry-run)."""
    files = int(conn.execute("SELECT COUNT(*) FROM files WHERE is_missing = 0").fetchone()[0])
    analyzed = int(
        conn.execute(
            "SELECT COUNT(*) FROM audio_analysis a JOIN files f ON f.id = a.file_id"
            " WHERE f.is_missing = 0 AND a.analyzer = ? AND a.analysis_version = ?",
            (analyzer.name, analyzer.version),
        ).fetchone()[0]
    )

    sql = "SELECT f.id AS file_id, f.path AS path FROM files f WHERE f.is_missing = 0"
    params: tuple[object, ...] = ()
    if not force:
        sql += (
            " AND NOT EXISTS (SELECT 1 FROM audio_analysis a"
            " WHERE a.file_id = f.id AND a.analyzer = ? AND a.analysis_version = ?)"
        )
        params = (analyzer.name, analyzer.version)
    sql += " ORDER BY f.path"
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)

    candidates = tuple(
        Candidate(file_id=int(row["file_id"]), path=str(row["path"]))
        for row in conn.execute(sql, params)
    )
    return AnalyzePlan(
        analyzer=analyzer.name,
        version=analyzer.version,
        files=files,
        analyzed=analyzed,
        candidates=candidates,
    )


def apply_plan(
    conn: sqlite3.Connection,
    plan: AnalyzePlan,
    analyzer: Analyzer,
    *,
    on_progress: ProgressCallback | None = None,
) -> AnalyzeResult:
    """Analisa cada candidato e grava o resultado (falhas vao para `scan_errors`)."""
    now = utcnow()
    total = len(plan.candidates)
    analyzed = 0
    errors: list[tuple[str, str]] = []

    for index, candidate in enumerate(plan.candidates, start=1):
        if on_progress is not None:
            on_progress(index, total, candidate.path)
        try:
            features = analyzer.analyze(Path(candidate.path))
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            errors.append((candidate.path, message))
            conn.execute(
                "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
                (candidate.path, message),
            )
            continue
        _store(conn, candidate.file_id, analyzer, features, now)
        analyzed += 1

    conn.commit()
    return AnalyzeResult(
        analyzer=analyzer.name,
        version=analyzer.version,
        analyzed=analyzed,
        failed=len(errors),
        errors=tuple(errors),
    )


def _store(
    conn: sqlite3.Connection,
    file_id: int,
    analyzer: Analyzer,
    features: TrackFeatures,
    analyzed_at: str,
) -> None:
    conn.execute(
        _INSERT,
        (
            file_id,
            analyzer.name,
            analyzer.version,
            features.bpm,
            features.key_camelot,
            features.key_open,
            features.energy,
            features.danceability,
            features.loudness_lufs,
            analyzed_at,
        ),
    )
