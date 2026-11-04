from datetime import UTC, datetime

import pytest

from djlife import db, planner
from djlife.ml import learning, vectors

MODEL = "fake"
VERSION = "v1"


def _insert_file(conn, path, is_missing=0):
    conn.execute(
        """INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(path), "wav", 100, 0.0, None, is_missing, "now", "now"),
    )
    return conn.execute("SELECT id FROM files ORDER BY id DESC LIMIT 1").fetchone()[0]


def _insert_track(conn, file_id):
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, "Track", "artist", "album", 180.0, "now"),
    )
    return conn.execute("SELECT id FROM tracks ORDER BY id DESC LIMIT 1").fetchone()[0]


def _genre(conn, slug, name, level=0):
    conn.execute("INSERT INTO genres(slug, name, level) VALUES (?, ?, ?)", (slug, name, level))
    return int(conn.execute("SELECT id FROM genres WHERE slug = ?", (slug,)).fetchone()[0])


def _label(conn, track_id, genre_id, source, created_at="now"):
    conn.execute(
        "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
        " VALUES (?, ?, ?, 'A', NULL, ?) ON CONFLICT(track_id, genre_id, source) DO NOTHING",
        (track_id, genre_id, source, created_at),
    )


def _embed(conn, file_id, vector, model=MODEL, version=VERSION):
    conn.execute(
        "INSERT INTO embeddings(file_id, model, model_version, dim, vector, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'now')",
        (file_id, model, version, len(vector), vectors.pack(vector)),
    )


@pytest.fixture
def learned_catalog(tmp_path):
    """Duas correcoes (`house`) + dois alvos: um parecido e um ortogonal."""
    conn = db.open_catalog(tmp_path / "learning.db")
    file_ids = [_insert_file(conn, tmp_path / f"{name}.wav") for name in ("a", "b", "c", "d")]
    track_ids = [_insert_track(conn, file_id) for file_id in file_ids]
    house = _genre(conn, "house", "House")
    for track_id in track_ids[:2]:
        _label(conn, track_id, house, "manual")
    for file_id, vector in zip(
        file_ids,
        [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.8, 0.6, 0.0), (-1.0, 0.0, 0.0)],
        strict=True,
    ):
        _embed(conn, file_id, vector)
    conn.commit()
    yield conn, track_ids, house
    conn.close()


def test_learn_build_plan_proposes_from_corrections(learned_catalog):
    conn, track_ids, house = learned_catalog

    plan = learning.build_plan(conn, MODEL, VERSION)

    assert plan.embedded == 4
    assert plan.references == 2
    assert plan.targets == 2
    assert plan.pending == 1
    proposal = plan.proposals[0]
    assert proposal.track_id == track_ids[2]
    assert proposal.genre_id == house
    assert proposal.genre == "house"
    assert proposal.confidence == "A"
    assert proposal.score == pytest.approx(1.0)
    assert len(proposal.votes) == 2


def test_learn_cold_start_without_corrections(tmp_path):
    conn = db.open_catalog(tmp_path / "empty.db")
    try:
        _insert_file(conn, tmp_path / "a.wav")
        conn.commit()

        plan = learning.build_plan(conn, MODEL, VERSION)

        assert plan.references == 0
        assert plan.pending == 0
    finally:
        conn.close()


def test_learn_min_similarity_filters(learned_catalog):
    conn, _, _ = learned_catalog
    plan = learning.build_plan(conn, MODEL, VERSION, min_similarity=0.9)
    assert plan.pending == 0


def test_learn_apply_writes_learned_with_model_version(learned_catalog):
    conn, track_ids, house = learned_catalog

    result = learning.apply_plan(conn, learning.build_plan(conn, MODEL, VERSION))

    assert result.written == 1
    row = conn.execute(
        "SELECT source, confidence, score, model_version FROM track_genres"
        " WHERE track_id = ? AND genre_id = ?",
        (track_ids[2], house),
    ).fetchone()
    assert row["source"] == "learned"
    assert row["confidence"] == "A"
    assert row["score"] == pytest.approx(1.0)
    assert row["model_version"] == VERSION


def test_learn_apply_recomputes_previous_result(learned_catalog):
    conn, _, _ = learned_catalog

    learning.apply_plan(conn, learning.build_plan(conn, MODEL, VERSION))
    result = learning.apply_plan(conn, learning.build_plan(conn, MODEL, VERSION))

    assert result.removed == 1
    assert result.written == 1
    total = conn.execute("SELECT COUNT(*) FROM track_genres WHERE source = 'learned'").fetchone()[0]
    assert total == 1


def test_learn_decay_halves_per_half_life():
    now = datetime(2026, 1, 1, tzinfo=UTC)

    fresh = learning._decay("2026-01-01T00:00:00+00:00", now=now, half_life_days=180.0)
    old = learning._decay("2025-07-05T00:00:00+00:00", now=now, half_life_days=180.0)

    assert fresh == pytest.approx(1.0)
    assert old == pytest.approx(0.5, abs=0.02)


def test_learn_decay_defaults_to_one_for_invalid_date():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert learning._decay("now", now=now, half_life_days=180.0) == 1.0


def test_precedence_learned_beats_embedding_loses_to_rules(tmp_path):
    conn = db.open_catalog(tmp_path / "precedence.db")
    try:
        house = _genre(conn, "house", "House")
        techno = _genre(conn, "techno", "Techno")
        tracks = []
        for name in ("a", "b", "c", "d"):
            file_id = _insert_file(conn, tmp_path / f"{name}.wav")
            tracks.append(_insert_track(conn, file_id))

        _label(conn, tracks[0], house, "learned")
        _label(conn, tracks[0], techno, "embedding")
        _label(conn, tracks[1], house, "learned")
        _label(conn, tracks[1], techno, "rules")
        _label(conn, tracks[2], house, "learned")
        _label(conn, tracks[2], techno, "manual")
        _label(conn, tracks[3], house, "learned")
        conn.commit()

        labels = planner.resolve_labels(conn)

        assert labels[tracks[0]] == ("House", "")
        assert labels[tracks[1]] == ("Techno", "")
        assert labels[tracks[2]] == ("Techno", "")
        assert labels[tracks[3]] == ("House", "")
    finally:
        conn.close()


def test_migrate_upgrades_v4_to_v5(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    db.initialize(conn)
    conn.execute("DROP TABLE feedback")
    conn.execute("ALTER TABLE track_genres DROP COLUMN model_version")
    conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
    conn.commit()
    assert db.schema_version(conn) == 4

    assert db.migrate(conn) == 5

    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(track_genres)")}
    assert "feedback" in tables
    assert "model_version" in columns
    conn.close()


def test_migrate_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    try:
        assert db.migrate(conn) == db.SCHEMA_VERSION
        assert db.migrate(conn) == db.SCHEMA_VERSION
    finally:
        conn.close()
