from pathlib import Path

from djlife import db, scanner


def _make(root: Path, name: str, data: bytes = b"x") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_iter_filters_extensions(tmp_path):
    _make(tmp_path, "a.mp3")
    _make(tmp_path, "sub/b.flac")
    _make(tmp_path, "ignore.txt")
    found = {
        item.path.name
        for item in scanner.iter_audio_files(tmp_path, frozenset({"mp3", "flac"}))
    }
    assert found == {"a.mp3", "b.flac"}


def test_scan_inserts_updates_and_marks_missing(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    library = tmp_path / "lib"
    track = _make(library, "a.mp3", b"abc")

    first = scanner.scan(conn, library, extensions=("mp3",))
    assert (first.seen, first.new, first.updated, first.missing) == (1, 1, 0, 0)
    row = conn.execute("SELECT * FROM files").fetchone()
    assert row["hash"] == scanner.file_hash(track)
    assert row["is_missing"] == 0

    second = scanner.scan(conn, library, extensions=("mp3",))
    assert (second.new, second.updated, second.missing) == (0, 0, 0)
    assert second.changed_ids == []

    track.write_bytes(b"abcdef")
    third = scanner.scan(conn, library, extensions=("mp3",))
    assert (third.new, third.updated) == (0, 1)
    assert third.changed_ids == [row["id"]]

    track.unlink()
    fourth = scanner.scan(conn, library, extensions=("mp3",))
    assert (fourth.seen, fourth.missing) == (0, 1)
    assert conn.execute("SELECT is_missing FROM files").fetchone()[0] == 1

    runs = conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
    assert runs == 4
    conn.close()


def test_scan_without_hash(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    library = tmp_path / "lib"
    _make(library, "a.mp3", b"abc")

    scanner.scan(conn, library, extensions=("mp3",), hash_files=False)
    assert conn.execute("SELECT hash FROM files").fetchone()[0] is None
    conn.close()
