"""Painel de download online (recurso premium) para a interface web.

Reaproveita `importer.probe`/`importer.download` em tarefas longas
(`jobs.TaskJob`) e aplica o gate de licenca (`premium.download`). O painel so
dispara as tarefas e faz polling; o download efetivo escreve no filesystem e,
por isso, a rota correspondente exige o token de administracao.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from djlife import importer, premium
from djlife.config import Config
from djlife.ui.jobs import TaskJob

DEFAULT_TARGET = "downloads"
FORMATS: tuple[str, ...] = (
    importer.DEFAULT_FORMAT,
    "m4a/bestaudio/best",
    "mp3/bestaudio/best",
)


class DownloadError(RuntimeError):
    """Entrada invalida (nenhuma URL ou destino que nao e pasta)."""


class DownloadUnavailable(RuntimeError):
    """Recurso premium indisponivel (licenca ausente ou backend nao instalado)."""


def clean_urls(raw: Any) -> list[str]:
    """Normaliza URLs coladas (texto multilinha, virgulas ou lista) sem repetir."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [chunk for line in raw.splitlines() for chunk in line.split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = [str(item) for item in raw]
    else:
        return []
    seen: list[str] = []
    for part in parts:
        url = part.strip()
        if url and url not in seen:
            seen.append(url)
    return seen


def _require_feature(cfg: Config) -> None:
    try:
        premium.require_feature(cfg, premium.DOWNLOAD_FEATURE)
    except premium.PremiumUnavailable as exc:
        raise DownloadUnavailable(str(exc)) from exc


def _require_backend() -> None:
    if not importer.available():
        raise DownloadUnavailable(
            "backend de download nao esta instalado. "
            f"Instale o extra premium: {importer.INSTALL_HINT}"
        )


def _target_dir(raw: Any) -> Path:
    text = str(raw).strip() if raw is not None else ""
    destination = Path(text or DEFAULT_TARGET).expanduser()
    if destination.exists() and not destination.is_dir():
        raise DownloadError(f"destino invalido (nao e uma pasta): {text}")
    return destination


def _audio_format(raw: Any) -> str:
    text = str(raw).strip() if raw is not None else ""
    return text or importer.DEFAULT_FORMAT


def status(cfg: Config) -> dict[str, Any]:
    """Estado do painel: licenca, backend e destino padrao (somente leitura)."""
    try:
        _require_feature(cfg)
        licensed = True
        reason: str | None = None
    except DownloadUnavailable as exc:
        licensed = False
        reason = str(exc)
    backend = importer.available()
    return {
        "feature": premium.DOWNLOAD_FEATURE,
        "licensed": licensed,
        "reason": reason,
        "backend_available": backend,
        "install": importer.INSTALL_HINT,
        "ready": licensed and backend,
        "default_target": DEFAULT_TARGET,
        "formats": list(FORMATS),
    }


def start_probe(cfg: Config, urls: Any) -> TaskJob:
    """Le os metadados das URLs (dry-run) em thread, sem baixar nada."""
    clean = clean_urls(urls)
    if not clean:
        raise DownloadError("informe ao menos uma URL")
    _require_feature(cfg)
    _require_backend()
    job = TaskJob(task="probe")

    def worker() -> None:
        try:
            candidates = importer.probe(clean)
            job.result = {
                "count": len(candidates),
                "items": [
                    {
                        "url": item.url,
                        "title": item.title,
                        "uploader": item.uploader,
                        "duration": item.duration,
                        "ext": item.ext,
                    }
                    for item in candidates
                ],
            }
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.message = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_download(
    cfg: Config,
    urls: Any,
    *,
    target: Any = None,
    audio_format: Any = None,
) -> TaskJob:
    """Baixa o audio das URLs para `target` em thread (escrita no filesystem)."""
    clean = clean_urls(urls)
    if not clean:
        raise DownloadError("informe ao menos uma URL")
    _require_feature(cfg)
    _require_backend()
    out_dir = _target_dir(target)
    fmt = _audio_format(audio_format)
    job = TaskJob(task="download")

    def worker() -> None:
        try:
            outcomes = importer.download(clean, target_dir=out_dir, audio_format=fmt)
            ok = sum(1 for outcome in outcomes if outcome.ok)
            job.result = {
                "target": str(out_dir),
                "total": len(outcomes),
                "ok": ok,
                "errors": len(outcomes) - ok,
                "scan_hint": f"djlife scan {out_dir}",
                "items": [
                    {
                        "url": outcome.url,
                        "path": str(outcome.path) if outcome.path else None,
                        "ok": outcome.ok,
                        "message": outcome.message,
                    }
                    for outcome in outcomes
                ],
            }
            job.status = "done"
        except Exception as exc:  # reportado na interface em vez de derrubar o servidor
            job.status = "error"
            job.message = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job
