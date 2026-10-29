from __future__ import annotations

from pathlib import Path
from typing import Any

from djlife.integrations.base import (
    SOFTWARE_REKORDBOX,
    DjTrack,
    IntegrationUnavailable,
    IntegrityReport,
    RelinkPlan,
    RelinkResult,
    backup_database,
    integrity_report,
)

EXTRA_HINT = 'Instale o extra: pip install -e ".[rekordbox]"'


def _load() -> Any:
    try:
        import pyrekordbox  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise IntegrationUnavailable(f"pyrekordbox nao instalado. {EXTRA_HINT}") from exc
    return pyrekordbox


def _open(db_path: Path | None) -> Any:
    pyrekordbox = _load()
    factory = getattr(pyrekordbox, "Rekordbox6Database", None) or pyrekordbox.MasterDatabase
    return factory(path=str(db_path)) if db_path is not None else factory()


def _content_path(content: Any) -> str | None:
    folder = getattr(content, "FolderPath", None)
    if not folder:
        return None
    candidate = Path(str(folder))
    name = getattr(content, "FileNameL", None)
    if name and candidate.suffix == "":
        return str(candidate / str(name))
    return str(candidate)


def _artist(content: Any) -> str | None:
    try:
        name = content.Artist.Name
    except (AttributeError, TypeError):
        return None
    return str(name) if name else None


def read_tracks(db_path: Path | None = None) -> tuple[DjTrack, ...]:
    """Le a colecao do Rekordbox via pyrekordbox (extra opcional)."""
    db = _open(db_path)
    tracks: list[DjTrack] = []
    for content in db.get_content():
        resolved = _content_path(content)
        if resolved is None:
            continue
        path = Path(resolved)
        title = getattr(content, "Title", None)
        tracks.append(
            DjTrack(
                software=SOFTWARE_REKORDBOX,
                ref_id=str(getattr(content, "ID", "")),
                stored=resolved,
                path=resolved,
                title=str(title) if title else None,
                artist=_artist(content),
                exists=path.exists(),
            )
        )
    return tuple(tracks)


def status(db_path: Path | None = None) -> IntegrityReport:
    return integrity_report(SOFTWARE_REKORDBOX, read_tracks(db_path))


def to_stored(new: str, original: str) -> str:
    """Preserva o estilo de separador do caminho original."""
    if "\\" not in original and "/" in original:
        return new.replace("\\", "/")
    return new


def relink(db_path: Path, plan: RelinkPlan, *, apply: bool = False) -> RelinkResult:
    """Atualiza FolderPath/FileNameL no master.db para os caminhos atuais do catalogo."""
    if not apply or plan.count == 0:
        return RelinkResult(software=SOFTWARE_REKORDBOX, applied=0)

    backup = backup_database(db_path)
    db = _open(db_path)
    by_id = {change.ref_id: change for change in plan.changes}
    applied = 0
    errors = 0
    for content in db.get_content():
        change = by_id.get(str(getattr(content, "ID", "")))
        if change is None:
            continue
        target = to_stored(change.new, change.old)
        content.FolderPath = target
        content.FileNameL = Path(target).name
        applied += 1
    try:
        db.commit()
    except Exception:  # noqa: BLE001 - erro do ORM de terceiro
        errors = applied
        applied = 0

    after = status(db_path) if errors == 0 else None
    return RelinkResult(
        software=SOFTWARE_REKORDBOX, applied=applied, backup=backup, errors=errors, after=after
    )
