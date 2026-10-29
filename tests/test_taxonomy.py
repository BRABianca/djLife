import pytest

from djlife import db, taxonomy


def test_normalize():
    assert taxonomy.normalize("Deep House") == "deephouse"
    assert taxonomy.normalize("Drum & Bass") == "drumbass"
    assert taxonomy.normalize("Nu-Disco") == "nudisco"


def test_default_taxonomy_loads():
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    assert tree.version == "0.1.0"
    assert len(tree.nodes) > 50
    assert tree.by_slug["house.deep_house"].name == "Deep House"
    assert tree.by_slug["house.deep_house"].parent_slug == "house"
    assert tree.by_slug["house.deep_house"].level == 1
    assert tree.by_slug["house"].level == 0


def test_alias_index_maps_tokens():
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    assert tree.alias_index["deephouse"] == "house.deep_house"
    assert tree.alias_index["dnb"] == "drum_and_bass"
    assert tree.alias_index["psy"] == "trance.psy"
    assert tree.alias_index["triphop"] == "ambient_downtempo.trip_hop"


def test_alias_index_does_not_contain_spaces():
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    assert all(" " not in token for token in tree.alias_index)


def test_sync_creates_tree(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    count = taxonomy.sync(conn, tree)
    assert count == len(tree.nodes)

    root_id = conn.execute("SELECT id FROM genres WHERE slug = 'house'").fetchone()["id"]
    child = conn.execute("SELECT parent_id FROM genres WHERE slug = 'house.deep_house'").fetchone()
    assert child["parent_id"] == root_id

    version = conn.execute("SELECT value FROM meta WHERE key = 'taxonomy_version'").fetchone()[0]
    assert version == "0.1.0"
    conn.close()


def test_sync_is_idempotent(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    taxonomy.sync(conn, tree)
    taxonomy.sync(conn, tree)
    total = conn.execute("SELECT COUNT(*) FROM genres").fetchone()[0]
    assert total == len(tree.nodes)
    conn.close()


def test_sync_deactivates_removed_slug(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    conn.execute("INSERT INTO genres(slug, name, level) VALUES ('legacy', 'Legacy', 0)")
    conn.commit()
    tree = taxonomy.load_taxonomy(taxonomy.default_taxonomy_path())
    taxonomy.sync(conn, tree)
    active = conn.execute("SELECT is_active FROM genres WHERE slug = 'legacy'").fetchone()[0]
    assert active == 0
    conn.close()


def test_duplicate_slug_rejected(tmp_path):
    path = tmp_path / "genres.yaml"
    path.write_text(
        'version: "t"\ngenres:\n'
        "  - slug: house\n    name: House\n"
        "  - slug: house\n    name: Casa\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Slug duplicado"):
        taxonomy.load_taxonomy(path)


def test_invalid_genres_section(tmp_path):
    path = tmp_path / "genres.yaml"
    path.write_text('version: "t"\ngenres: 3\n', encoding="utf-8")
    with pytest.raises(ValueError, match="deve ser uma lista"):
        taxonomy.load_taxonomy(path)
