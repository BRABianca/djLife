"""Download online (recurso premium).

O backend de download e importado tardiamente: sem o extra `premium` instalado,
os comandos degradam para `ImportUnavailable` em vez de quebrar o nucleo.
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
    """O backend de download (extra `premium`) nao esta instalado."""


class ImportFailed(RuntimeError):
    """Nao foi possivel ler os metadados de uma URL."""


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


def _backend() -> Any:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportUnavailable(
            f"backend de download nao esta instalado. Instale o extra premium: {INSTALL_HINT}"
        ) from exc
    return yt_dlp


def available() -> bool:
    """Indica se o backend de download (extra `premium`) esta disponivel no ambiente."""
    try:
        _backend()
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
    backend = _backend()
    options: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
    candidates: list[ImportCandidate] = []
    with backend.YoutubeDL(options) as ydl:
        for url in urls:
            try:
                info: dict[str, Any] = ydl.extract_info(url, download=False)
            except Exception as exc:  # erro de terceiro (URL indisponivel/geo): mensagem limpa
                raise ImportFailed(f"falha ao ler metadados de {url}: {exc}") from exc
            candidates.append(_candidate(url, info))
    return candidates


def download(
    urls: Sequence[str],
    *,
    target_dir: Path | str,
    audio_format: str = DEFAULT_FORMAT,
) -> list[DownloadOutcome]:
    """Baixa o audio das URLs para `target_dir` usando o backend de download."""
    backend = _backend()
    out_dir = Path(target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": audio_format,
        "outtmpl": str(out_dir / OUTPUT_TEMPLATE),
    }
    outcomes: list[DownloadOutcome] = []
    with backend.YoutubeDL(options) as ydl:
        for url in urls:
            try:
                info: dict[str, Any] = ydl.extract_info(url, download=True)
            except Exception as exc:  # erro de terceiro por item: nao interrompe o lote
                outcomes.append(DownloadOutcome(url, None, False, str(exc)))
                continue
            outcomes.append(DownloadOutcome(url, Path(ydl.prepare_filename(info)), True, "ok"))
    return outcomes
