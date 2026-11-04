import wave
from pathlib import Path

import pytest

from djlife import db
from djlife.analysis import camelot
from djlife.analysis.base import FULL_VERSION, TrackFeatures
from djlife.analysis.runner import apply_plan, build_plan, load_analyzer


class FakeAnalyzer:
    name = "fake"
    version = "t1"

    def __init__(self, features=None, error=None):
        self._features = features or TrackFeatures(bpm=128.0, key_camelot="8A", key_open="1d")
        self._error = error

    def analyze(self, path: Path) -> TrackFeatures:
        if self._error is not None:
            raise self._error
        return self._features


def _insert_file(conn, path, is_missing=0):
    conn.execute(
        """INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(path), "wav", 100, 0.0, None, is_missing, "now", "now"),
    )
    return conn.execute("SELECT id FROM files ORDER BY id DESC LIMIT 1").fetchone()[0]


@pytest.fixture
def catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    _insert_file(conn, tmp_path / "a.wav")
    _insert_file(conn, tmp_path / "b.wav")
    _insert_file(conn, tmp_path / "gone.wav", is_missing=1)
    conn.commit()
    yield conn
    conn.close()


def test_camelot_code():
    assert camelot.camelot_code(9, "minor") == "8A"
    assert camelot.camelot_code(0, "major") == "8B"
    assert camelot.camelot_code(11, "major") == "1B"


def test_open_key_code():
    assert camelot.open_key_code(0, "major") == "1d"
    assert camelot.open_key_code(9, "minor") == "1m"


def test_notations_pair():
    assert camelot.notations(0, "major") == ("8B", "1d")
    assert camelot.notations(9, "minor") == ("8A", "1m")


def test_describe():
    assert camelot.describe(9, "minor") == "A minor"
    assert camelot.describe(0, "major") == "C major"


@pytest.mark.parametrize("pitch_class,mode", [(12, "major"), (-1, "minor"), (3, "dorian")])
def test_camelot_rejects_invalid(pitch_class, mode):
    with pytest.raises(ValueError):
        camelot.camelot_code(pitch_class, mode)


def test_load_analyzer_invalid_backend():
    with pytest.raises(ValueError, match="backend invalido"):
        load_analyzer("traktor")


def test_load_analyzer_librosa():
    pytest.importorskip("librosa")
    analyzer = load_analyzer("librosa")
    assert analyzer.name == "librosa"
    assert analyzer.version == FULL_VERSION


def test_build_plan_lists_pending(catalog):
    plan = build_plan(catalog, FakeAnalyzer())
    assert plan.files == 2
    assert plan.analyzed == 0
    assert plan.pending == 2
    assert [Path(c.path).name for c in plan.candidates] == ["a.wav", "b.wav"]


def test_build_plan_limit(catalog):
    plan = build_plan(catalog, FakeAnalyzer(), limit=1)
    assert plan.pending == 1
    assert plan.files == 2


def test_apply_plan_stores_features(catalog):
    analyzer = FakeAnalyzer()
    plan = build_plan(catalog, analyzer)
    result = apply_plan(catalog, plan, analyzer)

    assert result.analyzed == 2
    assert result.failed == 0
    row = catalog.execute(
        "SELECT bpm, key_camelot, key_open, analyzer, analysis_version FROM audio_analysis"
        " ORDER BY file_id LIMIT 1"
    ).fetchone()
    assert row["bpm"] == pytest.approx(128.0)
    assert row["key_camelot"] == "8A"
    assert row["key_open"] == "1d"
    assert row["analyzer"] == "fake"
    assert row["analysis_version"] == "t1"


def test_apply_plan_is_idempotent(catalog):
    analyzer = FakeAnalyzer()
    plan = build_plan(catalog, analyzer)
    apply_plan(catalog, plan, analyzer)
    apply_plan(catalog, build_plan(catalog, analyzer, force=True), analyzer)

    total = catalog.execute("SELECT COUNT(*) FROM audio_analysis").fetchone()[0]
    assert total == 2


def test_build_plan_skips_analyzed(catalog):
    analyzer = FakeAnalyzer()
    apply_plan(catalog, build_plan(catalog, analyzer), analyzer)

    plan = build_plan(catalog, analyzer)
    assert plan.analyzed == 2
    assert plan.pending == 0

    forced = build_plan(catalog, analyzer, force=True)
    assert forced.pending == 2


def test_apply_plan_records_failure(catalog):
    analyzer = FakeAnalyzer(error=RuntimeError("audio corrompido"))
    plan = build_plan(catalog, analyzer)
    result = apply_plan(catalog, plan, analyzer)

    assert result.analyzed == 0
    assert result.failed == 2
    assert result.errors[0][1] == "audio corrompido"

    errors = catalog.execute("SELECT path, message FROM scan_errors").fetchall()
    assert len(errors) == 2
    assert errors[0]["message"] == "audio corrompido"
    assert catalog.execute("SELECT COUNT(*) FROM audio_analysis").fetchone()[0] == 0


def test_apply_plan_reports_progress(catalog):
    analyzer = FakeAnalyzer()
    seen: list[tuple[int, int, str]] = []

    def record(index: int, total: int, path: str) -> None:
        seen.append((index, total, path))

    apply_plan(catalog, build_plan(catalog, analyzer), analyzer, on_progress=record)

    assert [(index, total) for index, total, _ in seen] == [(1, 2), (2, 2)]


def test_librosa_analyze_end_to_end(tmp_path):
    pytest.importorskip("librosa")
    numpy = pytest.importorskip("numpy")

    path = tmp_path / "tone.wav"
    sample_rate = 22050
    t = numpy.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    tone = (0.5 * numpy.sin(2 * numpy.pi * 440 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(tone.tobytes())

    analyzer = load_analyzer("librosa")
    features = analyzer.analyze(path)
    assert isinstance(features, TrackFeatures)
