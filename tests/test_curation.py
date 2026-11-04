from pathlib import Path

import pytest

from djlife import curation, db, planner, taxonomy

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
    children:
      - slug: techno.minimal
        name: Minimal
"""


@pytest.fixture
def catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    source = tmp_path / "genres.yaml"
    source.write_text(TAXONOMY_YAML, encoding="utf-8")
    taxonomy.sync(conn, taxonomy.load_taxonomy(source))
    return conn


def genre_id(conn, slug: str) -> int:
    row = conn.execute("SELECT id FROM genres WHERE slug = ?", (slug,)).fetchone()
    return int(row["id"])


def add_track(
    conn,
    path: Path,
    *,
    title: str = "Track",
    artist: str = "DJ",
    entries: tuple[tuple[str, str, str], ...] = (),
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
    for slug, source, confidence in entries:
        conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
            " VALUES (?, (SELECT id FROM genres WHERE slug = ?), ?, ?, NULL, 'now')",
            (track_id, slug, source, confidence),
        )
    conn.commit()
    return track_id


def test_build_queue_flags_cross_source_conflict(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("techno.minimal", "rules", "B")),
    )

    items = curation.build_queue(catalog)

    assert len(items) == 1
    item = items[0]
    assert item.level == curation.LEVEL_DIVERGENTE
    assert item.labels["tags"] == ["House > Deep House"]
    assert item.labels["rules"] == ["Techno > Minimal"]
    assert item.suggestion.label == "House > Deep House"


def test_build_queue_ignores_agreement_between_sources(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("house.deep_house", "rules", "B")),
    )

    assert curation.build_queue(catalog) == []


def test_build_queue_ignores_single_source(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("techno.minimal", "tags", "A")),
    )

    assert curation.build_queue(catalog) == []


def test_build_queue_marks_same_root_as_ambiguous(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("house", "rules", "B")),
    )

    items = curation.build_queue(catalog)

    assert len(items) == 1
    assert items[0].level == curation.LEVEL_AMBIGUA


def test_build_queue_orders_divergent_before_ambiguous(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "z.wav",
        entries=(("house.deep_house", "tags", "A"), ("house", "rules", "B")),
    )
    add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house", "tags", "A"), ("techno", "rules", "B")),
    )

    items = curation.build_queue(catalog)

    assert [item.level for item in items] == [curation.LEVEL_DIVERGENTE, curation.LEVEL_AMBIGUA]


def test_build_queue_excludes_decided_tracks(catalog, tmp_path) -> None:
    track_id = add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("techno.minimal", "rules", "B")),
    )

    curation.record_decision(catalog, track_id, genre_id(catalog, "techno.minimal"))

    assert curation.build_queue(catalog) == []


def test_record_decision_becomes_primary(catalog, tmp_path) -> None:
    track_id = add_track(
        catalog,
        tmp_path / "a.wav",
        entries=(("house.deep_house", "tags", "A"), ("techno.minimal", "rules", "B")),
    )

    curation.record_decision(catalog, track_id, genre_id(catalog, "techno.minimal"))

    assert planner.resolve_labels(catalog)[track_id] == ("Techno", "Minimal")


def test_record_decision_is_idempotent(catalog, tmp_path) -> None:
    track_id = add_track(catalog, tmp_path / "a.wav")
    techno = genre_id(catalog, "techno.minimal")

    curation.record_decision(catalog, track_id, techno)
    curation.record_decision(catalog, track_id, techno)

    total = catalog.execute("SELECT COUNT(*) FROM track_genres WHERE source = 'manual'").fetchone()[
        0
    ]
    assert total == 1


def test_genre_choices_uses_root_and_leaf_labels(catalog) -> None:
    labels = {choice.label for choice in curation.genre_choices(catalog)}

    assert {"House", "House > Deep House", "Techno", "Techno > Minimal"} <= labels
