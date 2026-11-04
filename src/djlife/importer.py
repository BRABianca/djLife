"""Ingestao online com yt-dlp (recurso premium).

O `yt_dlp` e importado tardiamente: sem o extra `premium` instalado, os
comandos degradam para `ImportUnavailable` em vez de quebrar o nucleo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INSTALL_HINT = 'pip install -e ".[premium]"'
DEFAULT_FORMAT = "bestaudio/best"
OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"


class ImportUnavailable(RuntimeError):
    """O backend de importacao (yt-dlp) nao esta instalado."""


@dataclass(frozen=True)
class ImportCandidate:
    url: str
    title: str
    uploader: str | None
    duration: float | None
    ext: str | None


@dataclass(frozen=True)
class DownloadOutcome:
    url: str
    path: Path | None
    ok: bool
    message: str


def _ytdlp() -> Any:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportUnavailable(
            f"yt-dlp nao esta instalado. Instale o extra premium: {INSTALL_HINT}"
        ) from exc
    return yt_dlp


def available() -> bool:
    """Indica se o extra `premium` (yt-dlp) esta disponivel no ambiente."""
    try:
        _ytdlp()
    except ImportUnavailable:
        return False
    return True


def _candidate(url: str, info: dict[str, Any]) -> ImportCandidate:
    duration = info.get("duration")
    uploader = info.get("uploader") or info.get("channel")
    return ImportCandidate(
        url=url,
        title=str(info.get("title") or "-"),
        uploader=str(uploader) if uploader else None,
        duration=float(duration) if duration is not None else None,
        ext=str(info["ext"]) if info.get("ext") else None,
    )


def probe(urls: Sequence[str]) -> list[ImportCandidate]:
    """Le os metadados das URLs sem baixar (base do dry-run)."""
    yt_dlp = _ytdlp()
    options: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
    candidates: list[ImportCandidate] = []
    with yt_dlp.YoutubeDL(options) as ydl:
        for url in urls:
            info: dict[str, Any] = ydl.extract_info(url, download=False)
            candidates.append(_candidate(url, info))
    return candidates


def download(
    urls: Sequence[str],
    *,
    target_dir: Path | str,
    audio_format: str = DEFAULT_FORMAT,
) -> list[DownloadOutcome]:
    """Baixa o audio das URLs para `target_dir` usando yt-dlp."""
    yt_dlp = _ytdlp()
    out_dir = Path(target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": audio_format,
        "outtmpl": str(out_dir / OUTPUT_TEMPLATE),
    }
    outcomes: list[DownloadOutcome] = []
    with yt_dlp.YoutubeDL(options) as ydl:
        for url in urls:
            try:
                info: dict[str, Any] = ydl.extract_info(url, download=True)
            except Exception as exc:  # erro de terceiro por item: nao interrompe o lote
                outcomes.append(DownloadOutcome(url, None, False, str(exc)))
                continue
            outcomes.append(DownloadOutcome(url, Path(ydl.prepare_filename(info)), True, "ok"))
    return outcomes
