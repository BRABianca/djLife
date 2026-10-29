from pathlib import Path

import pytest

from djlife import db
from djlife.ml import neighbors, vectors
from djlife.ml.clap_backend import DIM, MODEL_ID, MODEL_VERSION, version_for
from djlife.ml.runner import apply_plan, build_plan, embedder_version, load_embedder

MODEL = "fake"
VERSION = "v1"


class FakeEmbedder:
    name = MODEL
    version = VERSION
    dim = 3

    def __init__(self, vector=(0.0, 0.0, 1.0), error=None):
        self._vector = vector
        self._error = error

    def embed(self, path: Path) -> tuple[float, ...]:
        if self._error is not None:
            raise self._error
        return self._vector


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
        (file_id, Path("x").name, "artist", "album", 180.0, "now"),
    )
    return conn.execute("SELECT id FROM tracks ORDER BY id DESC LIMIT 1").fetchone()[0]


@pytest.fixture
def catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    _insert_file(conn, tmp_path / "a.wav")
    _insert_file(conn, tmp_path / "b.wav")
    _insert_file(conn, tmp_path / "gone.wav", is_missing=1)
    conn.commit()
    yield conn
    conn.close()


def test_pack_unpack_roundtrip():
    blob = vectors.pack([0.5, -1.25, 3.0])
    assert len(blob) == 3 * vectors.FLOAT_BYTES
    assert vectors.unpack(blob) == pytest.approx((0.5, -1.25, 3.0))


def test_pack_rejects_empty():
    with pytest.raises(ValueError, match="vazio"):
        vectors.pack([])


def test_unpack_rejects_invalid():
    with pytest.raises(ValueError, match="invalido"):
        vectors.unpack(b"\x00\x01\x02")


def test_l2_normalize_unit_norm():
    normalized = vectors.l2_normalize([3.0, 4.0])
    assert normalized == pytest.approx((0.6, 0.8))


def test_l2_normalize_rejects_zero():
    with pytest.raises(ValueError, match="nulo"):
        vectors.l2_normalize([0.0, 0.0])


def test_cosine_orthogonal_and_identical():
    assert vectors.cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert vectors.cosine((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_cosine_rejects_dimension_mismatch():
    with pytest.raises(ValueError, match="incompativeis"):
        vectors.cosine((1.0, 0.0), (1.0, 0.0, 0.0))


def test_embedder_version_default_model():
    assert version_for() == f"{MODEL_ID}@{MODEL_VERSION}"
    assert embedder_version("clap") == f"{MODEL_ID}@{MODEL_VERSION}"
    assert DIM == 512


def test_load_embedder_invalid_backend():
    with pytest.raises(ValueError, match="embedder invalido"):
        load_embedder("musicnn")


def test_embedder_version_invalid_backend():
    with pytest.raises(ValueError, match="embedder invalido"):
        embedder_version("musicnn")


def test_build_plan_lists_pending(catalog):
    plan = build_plan(catalog, MODEL, VERSION)
    assert plan.files == 2
    assert plan.embedded == 0
    assert plan.pending == 2
    assert [Path(c.path).name for c in plan.candidates] == ["a.wav", "b.wav"]


def test_build_plan_limit(catalog):
    plan = build_plan(catalog, MODEL, VERSION, limit=1)
    assert plan.pending == 1
    assert plan.files == 2


def test_apply_plan_stores_vectors(catalog):
    embedder = FakeEmbedder(vector=(0.5, 0.5, 0.5))
    plan = build_plan(catalog, embedder.name, embedder.version)
    result = apply_plan(catalog, plan, embedder)

    assert result.embedded == 2
    assert result.failed == 0
    row = catalog.execute(
        "SELECT model, model_version, dim, vector FROM embeddings ORDER BY file_id LIMIT 1"
    ).fetchone()
    assert row["model"] == MODEL
    assert row["model_version"] == VERSION
    assert row["dim"] == 3
    assert vectors.unpack(row["vector"]) == pytest.approx((0.5, 0.5, 0.5))


def test_apply_plan_is_idempotent(catalog):
    embedder = FakeEmbedder()
    apply_plan(catalog, build_plan(catalog, MODEL, VERSION), embedder)
    apply_plan(catalog, build_plan(catalog, MODEL, VERSION, force=True), embedder)

    total = catalog.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    assert total == 2


def test_build_plan_skips_embedded(catalog):
    embedder = FakeEmbedder()
    apply_plan(catalog, build_plan(catalog, MODEL, VERSION), embedder)

    plan = build_plan(catalog, MODEL, VERSION)
    assert plan.embedded == 2
    assert plan.pending == 0

    forced = build_plan(catalog, MODEL, VERSION, force=True)
    assert forced.pending == 2


def test_apply_plan_records_failure(catalog):
    embedder = FakeEmbedder(error=RuntimeError("audio corrompido"))
    plan = build_plan(catalog, MODEL, VERSION)
    result = apply_plan(catalog, plan, embedder)

    assert result.embedded == 0
    assert result.failed == 2
    assert result.errors[0][1] == "audio corrompido"

    errors = catalog.execute("SELECT path, message FROM scan_errors").fetchall()
    assert len(errors) == 2
    assert catalog.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0


def test_apply_plan_reports_progress(catalog):
    embedder = FakeEmbedder()
    seen: list[tuple[int, int, str]] = []

    def record(index: int, total: int, path: str) -> None:
        seen.append((index, total, path))

    apply_plan(catalog, build_plan(catalog, MODEL, VERSION), embedder, on_progress=record)

    assert [(index, total) for index, total, _ in seen] == [(1, 2), (2, 2)]


def _labeled_catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "neighbors.db")
    file_ids = [_insert_file(conn, tmp_path / f"{name}.wav") for name in ("a", "b", "c", "d")]
    track_ids = [_insert_track(conn, file_id) for file_id in file_ids]
    conn.execute("INSERT INTO genres(slug, name, level) VALUES ('house', 'House', 0)")
    house_id = int(conn.execute("SELECT id FROM genres WHERE slug = 'house'").fetchone()[0])
    for track_id in track_ids[:2]:
        conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score,"
            " created_at) VALUES (?, ?, 'tags', 'A', NULL, 'now')",
            (track_id, house_id),
        )
    for file_id, vector in zip(
        file_ids,
        [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.8, 0.6, 0.0), (-1.0, 0.0, 0.0)],
        strict=True,
    ):
        conn.execute(
            "INSERT INTO embeddings(file_id, model, model_version, dim, vector, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'now')",
            (file_id, MODEL, VERSION, 3, vectors.pack(vector)),
        )
    conn.commit()
    return conn, track_ids, house_id


def test_neighbors_build_plan_proposes(tmp_path):
    conn, track_ids, house_id = _labeled_catalog(tmp_path)
    try:
        plan = neighbors.build_plan(conn, MODEL, VERSION)

        assert plan.embedded == 4
        assert plan.labeled == 2
        assert plan.targets == 2
        assert plan.pending == 1
        proposal = plan.proposals[0]
        assert proposal.track_id == track_ids[2]
        assert proposal.genre_id == house_id
        assert proposal.genre == "house"
        assert proposal.confidence == "A"
        assert proposal.neighbors == 2
    finally:
        conn.close()


def test_neighbors_min_similarity_filters(tmp_path):
    conn, _, _ = _labeled_catalog(tmp_path)
    try:
        plan = neighbors.build_plan(conn, MODEL, VERSION, min_similarity=0.9)
        assert plan.pending == 0
    finally:
        conn.close()


def test_neighbors_apply_writes_proposals(tmp_path):
    conn, track_ids, house_id = _labeled_catalog(tmp_path)
    try:
        plan = neighbors.build_plan(conn, MODEL, VERSION)
        result = neighbors.apply_plan(conn, plan)

        assert result.written == 1
        assert result.skipped == 0

        row = conn.execute(
            "SELECT source, confidence, score FROM track_genres"
            " WHERE track_id = ? AND genre_id = ?",
            (track_ids[2], house_id),
        ).fetchone()
        assert row["source"] == "embedding"
        assert row["confidence"] == "A"
        assert row["score"] == pytest.approx(1.0)
    finally:
        conn.close()


def test_neighbors_does_not_touch_tag_labels(tmp_path):
    conn, track_ids, _ = _labeled_catalog(tmp_path)
    try:
        neighbors.apply_plan(conn, neighbors.build_plan(conn, MODEL, VERSION))

        sources = {
            str(row["source"])
            for row in conn.execute(
                "SELECT source FROM track_genres WHERE track_id = ?", (track_ids[0],)
            )
        }
        assert sources == {"tags"}
    finally:
        conn.close()


def test_neighbors_apply_is_idempotent(tmp_path):
    conn, _, _ = _labeled_catalog(tmp_path)
    try:
        neighbors.apply_plan(conn, neighbors.build_plan(conn, MODEL, VERSION))

        plan = neighbors.build_plan(conn, MODEL, VERSION)
        assert plan.pending == 0

        result = neighbors.apply_plan(conn, plan)
        assert result.written == 0
    finally:
        conn.close()


def test_neighbors_without_embeddings(tmp_path):
    conn = db.open_catalog(tmp_path / "empty.db")
    try:
        plan = neighbors.build_plan(conn, MODEL, VERSION)
        assert plan.embedded == 0
        assert plan.pending == 0
    finally:
        conn.close()
