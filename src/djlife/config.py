from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from djlife.analysis.base import BACKENDS as ANALYSIS_BACKENDS
from djlife.analysis.base import DEFAULT_FAST_SECONDS
from djlife.db import default_db_path
from djlife.license import default_license_path, default_public_key_path
from djlife.ml.base import DEFAULT_MIN_SIMILARITY, DEFAULT_NEIGHBORS
from djlife.ml.base import EMBEDDERS as ML_EMBEDDERS
from djlife.registry import default_registry_path

DEFAULT_EXTENSIONS = ("mp3", "flac", "m4a", "aiff", "wav", "ogg", "opus")
FILE_STRATEGIES = ("hardlink", "move", "tag_only")
DEFAULT_PRIVATE_KEY = Path("secrets/license_private_key.pem")


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
class AnalysisConfig:
    backend: str = "librosa"
    fast: bool = False
    fast_seconds: float = DEFAULT_FAST_SECONDS


@dataclass(frozen=True)
class MlConfig:
    backend: str = "clap"
    model: str | None = None
    window_seconds: float | None = None
    neighbors: int = DEFAULT_NEIGHBORS
    min_similarity: float = DEFAULT_MIN_SIMILARITY


@dataclass(frozen=True)
class LicenseConfig:
    public_key: Path | None = None
    license_file: Path | None = None
    private_key: Path | None = None
    registry_file: Path | None = None
    admin_token: str | None = None

    @property
    def public_key_path(self) -> Path:
        return self.public_key or default_public_key_path()

    @property
    def license_path(self) -> Path:
        return self.license_file or default_license_path()

    @property
    def private_key_path(self) -> Path:
        return self.private_key or DEFAULT_PRIVATE_KEY

    @property
    def registry_path(self) -> Path:
        return self.registry_file or default_registry_path()


@dataclass(frozen=True)
class Config:
    library: LibraryConfig = field(default_factory=LibraryConfig)
    catalog: CatalogConfig = field(default_factory=CatalogConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    integrations: IntegrationsConfig = field(default_factory=IntegrationsConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    ml: MlConfig = field(default_factory=MlConfig)
    license: LicenseConfig = field(default_factory=LicenseConfig)

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

    # Le como utf-8-sig para tolerar BOM (editores no Windows gravam com BOM e o tomllib recusa).
    with source.open("rb") as fh:
        data = tomllib.loads(fh.read().decode("utf-8-sig"))

    library = data.get("library", {})
    catalog = data.get("catalog", {})
    classification = data.get("classification", {})
    files = data.get("files", {})
    integrations = data.get("integrations", {})
    analysis = data.get("analysis", {})
    ml = data.get("ml", {})
    license_data = data.get("license", {})

    strategy = files.get("strategy", FilesConfig.strategy)
    if strategy not in FILE_STRATEGIES:
        raise ValueError(
            f"files.strategy inválido: {strategy!r}. Use um de {', '.join(FILE_STRATEGIES)}."
        )

    backend = analysis.get("backend", AnalysisConfig.backend)
    if backend not in ANALYSIS_BACKENDS:
        raise ValueError(
            f"analysis.backend inválido: {backend!r}. Use um de {', '.join(ANALYSIS_BACKENDS)}."
        )

    ml_backend = ml.get("backend", MlConfig.backend)
    if ml_backend not in ML_EMBEDDERS:
        raise ValueError(
            f"ml.backend inválido: {ml_backend!r}. Use um de {', '.join(ML_EMBEDDERS)}."
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
        analysis=AnalysisConfig(
            backend=backend,
            fast=bool(analysis.get("fast", AnalysisConfig.fast)),
            fast_seconds=float(analysis.get("fast_seconds", DEFAULT_FAST_SECONDS)),
        ),
        ml=MlConfig(
            backend=ml_backend,
            model=ml.get("model"),
            window_seconds=(
                float(ml["window_seconds"]) if ml.get("window_seconds") is not None else None
            ),
            neighbors=int(ml.get("neighbors", DEFAULT_NEIGHBORS)),
            min_similarity=float(ml.get("min_similarity", DEFAULT_MIN_SIMILARITY)),
        ),
        license=LicenseConfig(
            public_key=_optional_path(license_data.get("public_key")),
            license_file=_optional_path(license_data.get("license_file")),
            private_key=_optional_path(license_data.get("private_key")),
            registry_file=_optional_path(license_data.get("registry_file")),
            admin_token=license_data.get("admin_token"),
        ),
    )


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _roots_line(roots: Sequence[str]) -> str:
    return "roots = [" + ", ".join(_toml_string(root) for root in roots) + "]"


def _upsert_key(lines: list[str], section: str, key: str, new_line: str) -> None:
    """Insere ou atualiza `key = ...` no bloco `section`, preservando o restante do arquivo.

    A edicao e cirurgica: comentarios, chaves nao modeladas e demais blocos permanecem
    intactos; valores multilinha da mesma chave sao substituidos por inteiro.
    """
    header = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)

    if header is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", new_line])
        return

    section_end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            section_end = i
            break

    pattern = re.compile(rf"\s*{re.escape(key)}\s*=")
    index = next((i for i in range(header + 1, section_end) if pattern.match(lines[i])), None)
    if index is None:
        lines.insert(header + 1, new_line)
        return

    end = index
    balance = lines[index].count("[") - lines[index].count("]")
    while balance > 0 and end + 1 < section_end:
        end += 1
        balance += lines[end].count("[") - lines[end].count("]")
    lines[index : end + 1] = [new_line]


def _write_lines(path: Path | str, lines: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def update_library_roots(path: Path | str, roots: Sequence[str]) -> Path:
    """Grava `library.roots` no arquivo de configuracao preservando o restante do conteudo.

    A edicao e cirurgica (linha do bloco `[library]`): comentarios, chaves nao modeladas
    e demais blocos permanecem intactos.
    """
    target = Path(path)
    lines: list[str] = []
    if target.exists():
        lines = target.read_text(encoding="utf-8-sig").splitlines()

    _upsert_key(lines, "library", "roots", _roots_line(roots))
    return _write_lines(target, lines)


def update_files_settings(path: Path | str, *, target: str, strategy: str) -> Path:
    """Grava `files.target` e `files.strategy`, preservando o restante do arquivo."""
    if strategy not in FILE_STRATEGIES:
        raise ValueError(
            f"files.strategy inválido: {strategy!r}. Use um de {', '.join(FILE_STRATEGIES)}."
        )
    config_file = Path(path)
    lines: list[str] = []
    if config_file.exists():
        lines = config_file.read_text(encoding="utf-8-sig").splitlines()

    _upsert_key(lines, "files", "strategy", f"strategy = {_toml_string(strategy)}")
    _upsert_key(lines, "files", "target", f"target = {_toml_string(target)}")
    return _write_lines(config_file, lines)
