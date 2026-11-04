import pytest

from djlife import classifier, db
from djlife.classifier import load_rules
from djlife.taxonomy import load_taxonomy, sync

MINI = """
version: "test"
genres:
  - slug: house
    name: House
    children:
      - slug: house.deep_house
        name: Deep House
        aliases: [deephouse]
  - slug: techno
    name: Techno
"""

RULES = """
version: "test"
rules:
  - name: Techno path
    field: path
    match: "techno"
    genre: techno
    confidence: B
"""


def _insert_file(conn, path):
    conn.execute(
        """INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
        (str(path), path.suffix.lstrip("."), 10, 0.0, None, "now", "now"),
    )
    return conn.execute("SELECT id FROM files ORDER BY id DESC LIMIT 1").fetchone()[0]


def _insert_track(conn, file_id, title="T", artist="A", album=None, duration=100.0):
    conn.execute(
        """INSERT INTO tracks(file_id, title, artist, album, duration, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, title, artist, album, duration, "now"),
    )
    return conn.execute("SELECT id FROM tracks ORDER BY id DESC LIMIT 1").fetchone()[0]


def _insert_tag(conn, file_id, key, value):
    conn.execute("INSERT INTO tags(file_id, key, value) VALUES (?, ?, ?)", (file_id, key, value))


@pytest.fixture
def catalog(tmp_path):
    tax_path = tmp_path / "genres.yaml"
    tax_path.write_text(MINI, encoding="utf-8")
    conn = db.open_catalog(tmp_path / "catalog.db")
    tree = load_taxonomy(tax_path)
    sync(conn, tree)
    yield conn, tree
    conn.close()


def _genre_id(conn, slug):
    return conn.execute("SELECT id FROM genres WHERE slug = ?", (slug,)).fetchone()["id"]


def test_tags_layer(catalog, tmp_path):
    conn, tree = catalog
    fid = _insert_file(conn, tmp_path / "deep.mp3")
    tid = _insert_track(conn, fid)
    _insert_tag(conn, fid, "TCON", "Deep House")
    conn.commit()

    result = classifier.classify(conn, tree)
    assert result.tracks == 1
    assert result.tagged == 1
    assert result.unresolved == 0
    assert result.inserted == 1

    row = conn.execute(
        "SELECT genre_id, source, confidence FROM track_genres WHERE track_id = ?", (tid,)
    ).fetchone()
    assert row["genre_id"] == _genre_id(conn, "house.deep_house")
    assert row["source"] == "tags"
    assert row["confidence"] == "A"


def test_rules_layer(catalog, tmp_path):
    conn, tree = catalog
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(RULES, encoding="utf-8")
    rules = load_rules(rules_path)

    fid = _insert_file(conn, tmp_path / "techno" / "x.mp3")
    tid = _insert_track(conn, fid)
    conn.commit()

    result = classifier.classify(conn, tree, rules)
    assert result.ruled == 1
    assert result.unresolved == 0

    row = conn.execute(
        "SELECT genre_id, source, confidence FROM track_genres WHERE track_id = ?", (tid,)
    ).fetchone()
    assert row["genre_id"] == _genre_id(conn, "techno")
    assert row["source"] == "rules"
    assert row["confidence"] == "B"


def test_unknown_tag_is_unresolved(catalog, tmp_path):
    conn, tree = catalog
    fid = _insert_file(conn, tmp_path / "polka.mp3")
    _insert_track(conn, fid)
    _insert_tag(conn, fid, "TCON", "Polka")
    conn.commit()

    result = classifier.classify(conn, tree)
    assert result.tagged == 0
    assert result.unresolved == 1
    assert result.inserted == 0


def test_classify_is_idempotent(catalog, tmp_path):
    conn, tree = catalog
    fid = _insert_file(conn, tmp_path / "deep.mp3")
    _insert_track(conn, fid)
    _insert_tag(conn, fid, "TCON", "House")
    conn.commit()

    classifier.classify(conn, tree)
    second = classifier.classify(conn, tree)
    assert second.inserted == 0
    total = conn.execute("SELECT COUNT(*) FROM track_genres").fetchone()[0]
    assert total == 1


def test_nothing_overwritten(catalog, tmp_path):
    conn, tree = catalog
    fid = _insert_file(conn, tmp_path / "deep.mp3")
    tid = _insert_track(conn, fid)
    _insert_tag(conn, fid, "TCON", "House")
    gid = _genre_id(conn, "house")
    conn.execute(
        """INSERT INTO track_genres(track_id, genre_id, source, confidence, created_at)
           VALUES (?, ?, 'tags', 'C', 'manual')""",
        (tid, gid),
    )
    conn.commit()

    result = classifier.classify(conn, tree)
    assert result.inserted == 0
    row = conn.execute(
        "SELECT confidence FROM track_genres WHERE track_id = ? AND source = 'tags'", (tid,)
    ).fetchone()
    assert row["confidence"] == "C"


def test_layers_filter(catalog, tmp_path):
    conn, tree = catalog
    fid = _insert_file(conn, tmp_path / "deep.mp3")
    _insert_track(conn, fid)
    _insert_tag(conn, fid, "TCON", "House")
    conn.commit()

    result = classifier.classify(conn, tree, layers=("rules",))
    assert result.tagged == 0
    assert result.unresolved == 1


def test_load_rules_missing_file(tmp_path):
    assert load_rules(tmp_path / "nao-existe.yaml") == ()


def test_load_rules_invalid_field(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        'rules:\n  - name: x\n    field: bpm\n    match: "1"\n    genre: house\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid"):
        load_rules(path)
