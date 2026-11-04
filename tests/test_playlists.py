from pathlib import Path

import pytest

from djlife import db, playlists, taxonomy

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
    duration: float | None = None,
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
        " VALUES (?, ?, ?, NULL, ?, 'now')",
        (file_id, title, artist, duration),
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


def test_build_plan_groups_by_genre(catalog, tmp_path) -> None:
    add_track(catalog, tmp_path / "in" / "a.wav", title="Groove", artist="DJ X", slug="house")
    add_track(catalog, tmp_path / "in" / "b.wav", title="Pulse", artist="DJ Y", slug="techno")

    plan = playlists.build_plan(catalog, out_dir=tmp_path / "pl")

    assert [playlist.relative.name for playlist in plan.playlists] == ["House.m3u8", "Techno.m3u8"]
    assert plan.total == 2


def test_build_plan_groups_by_subgenre(catalog, tmp_path) -> None:
    add_track(catalog, tmp_path / "in" / "a.wav", title="Groove", slug="house.deep_house")
    add_track(catalog, tmp_path / "in" / "b.wav", title="Pulse", slug="techno")

    plan = playlists.build_plan(catalog, out_dir=tmp_path / "pl", group_by="subgenre")

    relatives = {playlist.relative.as_posix() for playlist in plan.playlists}
    assert relatives == {"House/Deep House.m3u8", "Techno/Techno.m3u8"}


def test_build_plan_includes_unclassified(catalog, tmp_path) -> None:
    add_track(catalog, tmp_path / "in" / "a.wav", title="Sem Tags")

    plan = playlists.build_plan(catalog, out_dir=tmp_path / "pl")

    assert len(plan.playlists) == 1
    playlist = plan.playlists[0]
    assert playlist.genre == "_NaoClassificado"
    assert [track.title for track in playlist.tracks] == ["Sem Tags"]


def test_build_plan_rejects_invalid_group_by(catalog, tmp_path) -> None:
    with pytest.raises(ValueError, match="group_by"):
        playlists.build_plan(catalog, out_dir=tmp_path / "pl", group_by="bpm")


def test_write_creates_m3u8_with_relative_paths(catalog, tmp_path) -> None:
    add_track(
        catalog,
        tmp_path / "in" / "a.wav",
        title="Groove",
        artist="DJ X",
        duration=213.4,
        slug="house",
    )

    out_dir = tmp_path / "pl"
    result = playlists.write(playlists.build_plan(catalog, out_dir=out_dir))

    assert (result.playlists, result.tracks, result.errors) == (1, 1, 0)
    content = (out_dir / "House.m3u8").read_text(encoding="utf-8")
    assert content.splitlines() == [
        "#EXTM3U",
        "#EXTINF:213,DJ X - Groove",
        "../in/a.wav",
    ]
