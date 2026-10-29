"""Orquestra o calculo de embeddings sobre o catalogo (`embeddings`)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from djlife.ml import clap_backend, vectors
from djlife.ml.base import EMBEDDERS, Embedder
from djlife.scanner import utcnow

ProgressCallback = Callable[[int, int, str], None]

_INSERT = """
    INSERT INTO embeddings(file_id, model, model_version, dim, vector, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(file_id, model, model_version) DO UPDATE SET
        dim = excluded.dim,
        vector = excluded.vector,
        created_at = excluded.created_at
"""


def load_embedder(
    name: str,
    *,
    model: str | None = None,
    window_seconds: float | None = None,
) -> Embedder:
    """Instancia o backend pedido, sinalizando cedo se o extra nao estiver presente."""
    if name == clap_backend.NAME:
        return clap_backend.create(model_id=model, window_seconds=window_seconds)
    raise ValueError(f"embedder invalido: {name!r}. Use um de {', '.join(EMBEDDERS)}.")


def embedder_version(name: str, model: str | None = None) -> str:
    """`model_version` de um backend, sem carregar modelo nem importar o extra."""
    if name == clap_backend.NAME:
        return clap_backend.version_for(model)
    raise ValueError(f"embedder invalido: {name!r}. Use um de {', '.join(EMBEDDERS)}.")


@dataclass(frozen=True)
class Candidate:
    file_id: int
    path: str


@dataclass(frozen=True)
class EmbedPlan:
    embedder: str
    version: str
    files: int
    embedded: int
    candidates: tuple[Candidate, ...]

    @property
    def pending(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class EmbedResult:
    embedder: str
    version: str
    embedded: int
    failed: int
    errors: tuple[tuple[str, str], ...]


def build_plan(
    conn: sqlite3.Connection,
    name: str,
    version: str,
    *,
    limit: int | None = None,
    force: bool = False,
) -> EmbedPlan:
    """Seleciona os arquivos pendentes de embedding (dry-run, sem carregar o backend)."""
    files = int(conn.execute("SELECT COUNT(*) FROM files WHERE is_missing = 0").fetchone()[0])
    embedded = int(
        conn.execute(
            "SELECT COUNT(*) FROM embeddings e JOIN files f ON f.id = e.file_id"
            " WHERE f.is_missing = 0 AND e.model = ? AND e.model_version = ?",
            (name, version),
        ).fetchone()[0]
    )

    sql = "SELECT f.id AS file_id, f.path AS path FROM files f WHERE f.is_missing = 0"
    params: tuple[object, ...] = ()
    if not force:
        sql += (
            " AND NOT EXISTS (SELECT 1 FROM embeddings e"
            " WHERE e.file_id = f.id AND e.model = ? AND e.model_version = ?)"
        )
        params = (name, version)
    sql += " ORDER BY f.path"
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)

    candidates = tuple(
        Candidate(file_id=int(row["file_id"]), path=str(row["path"]))
        for row in conn.execute(sql, params)
    )
    return EmbedPlan(
        embedder=name,
        version=version,
        files=files,
        embedded=embedded,
        candidates=candidates,
    )


def apply_plan(
    conn: sqlite3.Connection,
    plan: EmbedPlan,
    embedder: Embedder,
    *,
    on_progress: ProgressCallback | None = None,
) -> EmbedResult:
    """Calcula o embedding de cada candidato e grava o vetor (falhas em `scan_errors`)."""
    now = utcnow()
    total = len(plan.candidates)
    embedded = 0
    errors: list[tuple[str, str]] = []

    for index, candidate in enumerate(plan.candidates, start=1):
        if on_progress is not None:
            on_progress(index, total, candidate.path)
        try:
            vector = embedder.embed(Path(candidate.path))
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            errors.append((candidate.path, message))
            conn.execute(
                "INSERT INTO scan_errors(run_id, path, message) VALUES (NULL, ?, ?)",
                (candidate.path, message),
            )
            continue
        _store(conn, candidate.file_id, embedder, vectors.pack(vector), now)
        embedded += 1

    conn.commit()
    return EmbedResult(
        embedder=embedder.name,
        version=embedder.version,
        embedded=embedded,
        failed=len(errors),
        errors=tuple(errors),
    )


def _store(
    conn: sqlite3.Connection,
    file_id: int,
    embedder: Embedder,
    blob: bytes,
    created_at: str,
) -> None:
    conn.execute(
        _INSERT,
        (
            file_id,
            embedder.name,
            embedder.version,
            len(blob) // vectors.FLOAT_BYTES,
            blob,
            created_at,
        ),
    )
