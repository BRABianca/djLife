"""Curadoria assistida (recurso premium) na interface web.

Expoe a fila de conflitos de genero (`curation.build_queue`) e grava a decisao
manual do usuario (`curation.record_decision`, ``source='manual'``), que passa a
ser a classificacao primaria e realimenta a camada ``learned``. A leitura da fila
nao altera nada; a escrita toca o catalogo e, por isso, a rota correspondente
exige o token de administracao e o gate de licenca
(``premium.assisted_curation``).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from djlife import curation, db, premium
from djlife.config import Config

FEATURE = premium.ASSISTED_CURATION_FEATURE


class CurationError(RuntimeError):
    """Entrada invalida da curadoria (catalogo ausente ou ids invalidos)."""


class CurationUnavailable(RuntimeError):
    """Recurso premium indisponivel (licenca sem `premium.assisted_curation`)."""


def _open(cfg: Config) -> sqlite3.Connection:
    path = cfg.db_path
    if not path.exists():
        raise CurationError(f"catalogo inexistente: {path}")
    return db.open_catalog(path)


def _gate(cfg: Config) -> tuple[bool, str | None]:
    try:
        premium.require_feature(cfg, FEATURE)
    except premium.PremiumUnavailable as exc:
        return False, str(exc)
    return True, None


def _require_feature(cfg: Config) -> None:
    licensed, reason = _gate(cfg)
    if not licensed:
        raise CurationUnavailable(reason or "recurso premium indisponivel")


def _payload(conn: sqlite3.Connection) -> tuple[list[Any], list[Any]]:
    return curation.build_queue(conn), curation.genre_choices(conn)


def queue_payload(cfg: Config) -> dict[str, Any]:
    """Fila de conflitos, generos de destino e estado do gate (somente leitura)."""
    licensed, reason = _gate(cfg)
    items: list[Any] = []
    choices: list[Any] = []
    if cfg.db_path.exists():
        conn = _open(cfg)
        try:
            items, choices = _payload(conn)
        finally:
            conn.close()
    return {
        "feature": FEATURE,
        "licensed": licensed,
        "reason": reason,
        "ready": licensed,
        "total": len(items),
        "items": [
            {
                "track_id": item.track_id,
                "file_id": item.file_id,
                "path": item.path,
                "title": item.title,
                "artist": item.artist,
                "level": item.level,
                "suggestion": {
                    "genre_id": item.suggestion.genre_id,
                    "label": item.suggestion.label,
                    "source": item.suggestion.source,
                },
                "signals": [
                    {
                        "source": signal.source,
                        "confidence": signal.confidence,
                        "genre_id": signal.genre_id,
                        "label": signal.label,
                    }
                    for signal in item.signals
                ],
            }
            for item in items
        ],
        "choices": [
            {"genre_id": choice.genre_id, "label": choice.label, "slug": choice.slug}
            for choice in choices
        ],
    }


def decide(
    cfg: Config, track_id: Any, genre_id: Any, *, operator: str | None = None
) -> dict[str, Any]:
    """Grava a decisao manual (`source='manual'`) e realimenta o aprendizado."""
    _require_feature(cfg)
    try:
        track = int(track_id)
        genre = int(genre_id)
    except (TypeError, ValueError) as exc:
        raise CurationError("informe track_id e genre_id validos") from exc
    if track <= 0 or genre <= 0:
        raise CurationError("informe track_id e genre_id validos")
    conn = _open(cfg)
    try:
        if conn.execute("SELECT 1 FROM genres WHERE id = ?", (genre,)).fetchone() is None:
            raise CurationError(f"genero inexistente: {genre}")
        curation.record_decision(conn, track, genre, operator=operator)
        pending = len(curation.build_queue(conn))
    finally:
        conn.close()
    return {"track_id": track, "genre_id": genre, "pending": pending}
