import os
from pathlib import Path

import pytest

from djlife import db, planner, taxonomy

TAXONOMY_YAML = """
version: "9.9.9"
genres:
  - slug: house
    name: House
    children:
      - slug: house.deep_house
        name: Deep House
  - slug: techno
    name: Techno
"""

TEMPLATE = "{genre}/{subgenre}/{artist} - {title}"


@pytest.fixture
def catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    source = tmp_path / "genres.yaml"
    source.write_text(TAXONOMY_YAML, encoding="utf-8")
    taxonomy.sync(conn, taxonomy.load_taxonomy(source))
    return conn


def add_track(
    conn,
    path: Path,
    *,
    title: str | None = None,
    artist: str | None = None,
    slug: str | None = None,
) -> int:
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, NULL, 0, 'now', 'now')",
        (str(path), path.suffix.lstrip("."), 2, 0.0),
    )
    file_id = int(conn.execute("SELECT MAX(id) AS id FROM files").fetchone()["id"])
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (?, ?, ?, NULL, NULL, 'now')",
        (file_id, title, artist),
    )
    track_id = int(conn.execute("SELECT MAX(id) AS id FROM tracks").fetchone()["id"])
    if slug is not None:
        conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
            " VALUES (?, (SELECT id FROM genres WHERE slug = ?), 'tags', 'A', NULL, 'now')",
            (track_id, slug),
        )
    conn.commit()
    return track_id


def build(conn, target: Path, strategy: str = "hardlink") -> planner.Plan:
    return planner.build_plan(
        conn,
        target=target,
        template=TEMPLATE,
        unknown_dir=planner.DEFAULT_UNKNOWN_DIR,
        strategy=strategy,
    )


def test_render_relative_sanitizes_components() -> None:
    path = planner.render_relative(
        TEMPLATE,
        {"genre": "House", "subgenre": "Deep House", "artist": "AC/DC", "title": "A:B"},
    )
    assert path.parts == ("House", "Deep House", "AC_DC - A_B")


def test_render_relative_drops_empty_component() -> None:
    path = planner.render_relative(
        "{genre}/{subgenre}/{title}", {"genre": "Techno", "subgenre": "", "title": "Track"}
    )
    assert path.parts == ("Techno", "Track")


def test_render_relative_rejects_unknown_placeholder() -> None:
    with pytest.raises(ValueError):
        planner.render_relative("{genre}/{nope}", {"genre": "House"})


def test_build_plan_projects_classified_track(catalog, tmp_path) -> None:
    src = tmp_path / "in" / "a.wav"
    add_track(catalog, src, title="Groove", artist="DJ X", slug="house.deep_house")

    built = build(catalog, tmp_path / "out")
    item = built.items[0]
    assert item.status == planner.STATUS_READY
    assert item.genre == "House"
    assert item.subgenre == "Deep House"
    assert item.dst == tmp_path / "out" / "House" / "Deep House" / "DJ X - Groove.wav"


def test_build_plan_marks_unclassified(catalog, tmp_path) -> None:
    add_track(catalog, tmp_path / "in" / "a.wav", title="Groove", artist="DJ X")

    built = build(catalog, tmp_path / "out")
    item = built.items[0]
    assert item.status == planner.STATUS_UNCLASSIFIED
    assert item.dst is None
    assert item.genre == planner.DEFAULT_UNKNOWN_DIR


def test_build_plan_falls_back_to_filename(tmp_path, catalog) -> None:
    add_track(catalog, tmp_path / "in" / "Sem Tags.wav", slug="techno")

    built = build(catalog, tmp_path / "out")
    item = built.items[0]
    assert item.dst is not None
    assert item.dst.name == f"{planner.UNKNOWN_ARTIST} - Sem Tags.wav"


def test_build_plan_detects_conflict_and_existing(catalog, tmp_path, make_wav) -> None:
    src = make_wav(tmp_path / "in" / "a.wav")
    add_track(catalog, src, title="Groove", artist="DJ X", slug="house.deep_house")
    target = tmp_path / "out"

    conflict = target / "House" / "Deep House" / "DJ X - Groove.wav"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"outro conteudo")

    built = build(catalog, target)
    assert built.items[0].status == planner.STATUS_CONFLICT


def test_build_plan_detects_already_linked(catalog, tmp_path, make_wav) -> None:
    src = make_wav(tmp_path / "in" / "a.wav")
    add_track(catalog, src, title="Groove", artist="DJ X", slug="house.deep_house")
    target = tmp_path / "out"

    linked = target / "House" / "Deep House" / "DJ X - Groove.wav"
    linked.parent.mkdir(parents=True)
    os.link(src, linked)

    built = build(catalog, target)
    assert built.items[0].status == planner.STATUS_EXISTS


def test_build_plan_suffixes_collisions(catalog, tmp_path) -> None:
    add_track(catalog, tmp_path / "in" / "a.wav", title="Groove", artist="DJ X", slug="techno")
    add_track(catalog, tmp_path / "in" / "b.wav", title="Groove", artist="DJ X", slug="techno")

    built = build(catalog, tmp_path / "out")
    names = [item.dst.name for item in built.items if item.dst is not None]
    assert names == ["DJ X - Groove.wav", "DJ X - Groove (2).wav"]
