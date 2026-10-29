import csv
import json

import pytest

from djlife import db, report


def _insert_file(conn, path, size=100, is_missing=0):
    conn.execute(
        """INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(path), path.suffix.lstrip("."), size, 0.0, None, is_missing, "now", "now"),
    )
    return conn.execute("SELECT id FROM files ORDER BY id DESC LIMIT 1").fetchone()[0]


def _insert_track(conn, file_id, title=None, artist=None, album=None, duration=180.0):
    conn.execute(
        """INSERT INTO tracks(file_id, title, artist, album, duration, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, title, artist, album, duration, "now"),
    )


def _insert_tag(conn, file_id, key, value):
    conn.execute(
        "INSERT INTO tags(file_id, key, value) VALUES (?, ?, ?)",
        (file_id, key, value),
    )


@pytest.fixture
def catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    fid = _insert_file(conn, tmp_path / "a.mp3", size=200)
    _insert_track(conn, fid, title="Sunrise", artist="Aria", album="Dawn", duration=240.0)
    _insert_tag(conn, fid, "TBPM", "128")
    _insert_tag(conn, fid, "TKEY", "8A")
    _insert_tag(conn, fid, "TCON", "House")

    fid2 = _insert_file(conn, tmp_path / "b.flac", size=300)
    _insert_track(conn, fid2, title="Nightfall", artist="Aria", duration=180.0)
    _insert_tag(conn, fid2, "TBPM", "124")

    conn.commit()
    yield conn
    conn.close()


def test_fetch_tracks(catalog):
    rows = report.fetch_tracks(catalog)
    assert len(rows) == 2
    assert rows[0].path.endswith("a.mp3")
    assert rows[0].bpm == "128"
    assert rows[0].key == "8A"
    assert rows[0].genre == "House"


def test_search_by_title(catalog):
    assert len(report.search(catalog, "Sunrise")) == 1
    assert len(report.search(catalog, "sunrise")) == 1
    assert report.search(catalog, "Sunrise")[0].artist == "Aria"
    assert report.search(catalog, "inexistente") == []


def test_search_limit(catalog):
    rows = report.search(catalog, "Aria", limit=1)
    assert len(rows) == 1


def test_collect_stats(catalog):
    data = report.collect_stats(catalog)
    assert data.files == 2
    assert data.tracks == 2
    assert data.missing == 0
    assert data.total_duration == pytest.approx(420.0)
    assert ("mp3", 1) in data.by_extension
    coverage = dict((label, filled) for label, filled, _ in data.coverage)
    assert coverage["Titulo"] == 2
    assert coverage["BPM"] == 2
    assert coverage["Tonalidade"] == 1
    assert coverage["Genero (tag)"] == 1


def test_export_csv(catalog, tmp_path):
    out = tmp_path / "out.csv"
    count = report.export(catalog, out)
    assert count == 2
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["title"] == "Sunrise"


def test_export_json(catalog, tmp_path):
    out = tmp_path / "out.json"
    count = report.export(catalog, out, fmt="json")
    assert count == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload[0]["bpm"] == "128"


def test_export_unsupported_format(catalog, tmp_path):
    with pytest.raises(ValueError, match="Formato nao suportado"):
        report.export(catalog, tmp_path / "out.xml")
