from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from djlife.db import default_db_path

DEFAULT_EXTENSIONS = ("mp3", "flac", "m4a", "aiff", "wav", "ogg", "opus")
FILE_STRATEGIES = ("hardlink", "move", "tag_only")


@dataclass(frozen=True)
class LibraryConfig:
    roots: tuple[Path, ...] = ()
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    follow_symlinks: bool = False


@dataclass(frozen=True)
class CatalogConfig:
    path: Path | None = None
    hash_algorithm: str = "blake2b"
    hash_files: bool = True


@dataclass(frozen=True)
class ClassificationConfig:
    taxonomy: str = "genres.yaml"
    local_taxonomy: str = "genres.local.yaml"
    enable: tuple[str, ...] = ("tags", "rules")


@dataclass(frozen=True)
class FilesConfig:
    strategy: str = "hardlink"
    target: Path | None = None
    quarantine_dir: Path | None = None
    template: str = "{genre}/{subgenre}/{artist} - {title}"
    unknown_dir: str = "_NaoClassificado"


@dataclass(frozen=True)
class IntegrationsConfig:
    dj_software: tuple[str, ...] = ()
    rekordbox_db: Path | None = None
    serato_db: Path | None = None
    serato_dir: Path | None = None


@dataclass(frozen=True)
class Config:
    library: LibraryConfig = field(default_factory=LibraryConfig)
    catalog: CatalogConfig = field(default_factory=CatalogConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    integrations: IntegrationsConfig = field(default_factory=IntegrationsConfig)

    @property
    def db_path(self) -> Path:
        return self.catalog.path or default_db_path()


def _as_paths(values: list[str] | tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(Path(v) for v in values)


def _as_extensions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(v.lower().lstrip(".") for v in values)


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def load_config(path: Path | str | None = None) -> Config:
    source = Path(path) if path else Path("djlife.toml")
    if not source.exists():
        return Config()

    with source.open("rb") as fh:
        data = tomllib.load(fh)

    library = data.get("library", {})
    catalog = data.get("catalog", {})
    classification = data.get("classification", {})
    files = data.get("files", {})
    integrations = data.get("integrations", {})

    strategy = files.get("strategy", FilesConfig.strategy)
    if strategy not in FILE_STRATEGIES:
        raise ValueError(
            f"files.strategy inválido: {strategy!r}. Use um de {', '.join(FILE_STRATEGIES)}."
        )

    return Config(
        library=LibraryConfig(
            roots=_as_paths(library.get("roots", ())),
            extensions=_as_extensions(library.get("extensions", DEFAULT_EXTENSIONS)),
            follow_symlinks=bool(library.get("follow_symlinks", False)),
        ),
        catalog=CatalogConfig(
            path=_optional_path(catalog.get("path")),
            hash_algorithm=catalog.get("hash_algorithm", CatalogConfig.hash_algorithm),
            hash_files=bool(catalog.get("hash_files", True)),
        ),
        classification=ClassificationConfig(
            taxonomy=classification.get("taxonomy", ClassificationConfig.taxonomy),
            local_taxonomy=classification.get(
                "local_taxonomy", ClassificationConfig.local_taxonomy
            ),
            enable=tuple(classification.get("enable", ("tags", "rules"))),
        ),
        files=FilesConfig(
            strategy=strategy,
            target=_optional_path(files.get("target")),
            quarantine_dir=_optional_path(files.get("quarantine_dir")),
            template=files.get("template", FilesConfig.template),
            unknown_dir=files.get("unknown_dir", FilesConfig.unknown_dir),
        ),
        integrations=IntegrationsConfig(
            dj_software=tuple(integrations.get("dj_software", ())),
            rekordbox_db=_optional_path(integrations.get("rekordbox_db")),
            serato_db=_optional_path(integrations.get("serato_db")),
            serato_dir=_optional_path(integrations.get("serato_dir")),
        ),
    )
