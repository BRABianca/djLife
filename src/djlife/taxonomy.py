from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclass(frozen=True)
class GenreNode:
    slug: str
    name: str
    level: int
    parent_slug: str | None
    aliases: tuple[str, ...] = ()
    discogs: tuple[str, ...] = ()
    beatport: tuple[str, ...] = ()
    musicbrainz: tuple[str, ...] = ()


@dataclass(frozen=True)
class Taxonomy:
    version: str
    source: Path
    nodes: tuple[GenreNode, ...]
    by_slug: dict[str, GenreNode]
    alias_index: dict[str, str]


def default_taxonomy_path() -> Path:
    return Path(__file__).with_name("genres.yaml")


def _build(raw: list[Any], depth: int, parent_slug: str | None, out: list[GenreNode]) -> None:
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Cada genero deve ser um mapa com 'slug' e 'name'.")
        slug = str(entry["slug"])
        name = str(entry["name"])
        out.append(
            GenreNode(
                slug=slug,
                name=name,
                level=depth,
                parent_slug=parent_slug,
                aliases=_as_str_tuple(entry.get("aliases")),
                discogs=_as_str_tuple(entry.get("discogs")),
                beatport=_as_str_tuple(entry.get("beatport")),
                musicbrainz=_as_str_tuple(entry.get("musicbrainz")),
            )
        )
        children = entry.get("children") or []
        if not isinstance(children, list):
            raise ValueError(f"'children' de {slug!r} deve ser uma lista.")
        _build(children, depth + 1, slug, out)


def load_taxonomy(path: Path | str) -> Taxonomy:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Taxonomia invalida: {source}")
    raw = data.get("genres") or []
    if not isinstance(raw, list):
        raise ValueError("'genres' deve ser uma lista.")

    nodes: list[GenreNode] = []
    _build(raw, 0, None, nodes)

    by_slug: dict[str, GenreNode] = {}
    alias_index: dict[str, str] = {}
    for node in nodes:
        if node.slug in by_slug:
            raise ValueError(f"Slug duplicado na taxonomia: {node.slug}")
        by_slug[node.slug] = node
        tokens = {normalize(node.slug.rsplit(".", 1)[-1]), normalize(node.name)}
        tokens.update(normalize(alias) for alias in node.aliases)
        tokens.discard("")
        for token in tokens:
            alias_index[token] = node.slug

    return Taxonomy(
        version=str(data.get("version", "0.0.0")),
        source=source,
        nodes=tuple(nodes),
        by_slug=by_slug,
        alias_index=alias_index,
    )


def sync(conn: sqlite3.Connection, taxonomy: Taxonomy) -> int:
    ids: dict[str, int] = {}
    for node in taxonomy.nodes:
        parent_id = ids.get(node.parent_slug) if node.parent_slug else None
        conn.execute(
            """INSERT INTO genres(slug, name, parent_id, level, is_active, replaced_by)
               VALUES (?, ?, ?, ?, 1, NULL)
               ON CONFLICT(slug) DO UPDATE SET
                   name = excluded.name,
                   parent_id = excluded.parent_id,
                   level = excluded.level,
                   is_active = 1""",
            (node.slug, node.name, parent_id, node.level),
        )
        row = conn.execute("SELECT id FROM genres WHERE slug = ?", (node.slug,)).fetchone()
        assert row is not None
        ids[node.slug] = int(row["id"])

    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE genres SET is_active = 0 WHERE slug NOT IN ({placeholders})",
            tuple(ids),
        )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('taxonomy_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (taxonomy.version,),
    )
    conn.commit()
    return len(ids)
