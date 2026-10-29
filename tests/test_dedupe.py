from pathlib import Path

import pytest

from djlife import db, dedupe


def _catalog(tmp_path):
    return db.open_catalog(tmp_path / "catalog.db")


def _file(
    conn,
    path: Path,
    *,
    hash: str | None = None,
    duration: float | None = None,
    is_missing: int = 0,
) -> int:
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES (?, ?, 2, 0.0, ?, ?, 'now', 'now')",
        (str(path), path.suffix.lstrip("."), hash, is_missing),
    )
    file_id = int(conn.execute("SELECT MAX(id) AS id FROM files").fetchone()["id"])
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (?, NULL, NULL, NULL, ?, 'now')",
        (file_id, duration),
    )
    conn.commit()
    return file_id


def _tag(conn, file_id: int, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO tags(file_id, namespace, key, value) VALUES (?, 'id3', ?, ?)",
        (file_id, key, value),
    )
    conn.commit()


def _fingerprint(conn, file_id: int, value: str) -> None:
    conn.execute(
        "INSERT INTO fingerprints(file_id, fingerprint, duration, source, computed_at)"
        " VALUES (?, ?, 1.0, 'chromaprint', 'now')",
        (file_id, value),
    )
    conn.commit()


def test_hash_groups_and_prefers_quality(tmp_path) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="abc")
    keeper_id = _file(conn, tmp_path / "b.flac", hash="abc")

    result = dedupe.find_duplicates(conn)

    assert result.by_kind == [("hash", 1)]
    assert result.redundant == 1
    keeper = next(m for m in result.groups[0].members if m.is_keeper)
    assert keeper.file_id == keeper_id
    conn.close()


def test_hash_groups_prefers_longest_duration(tmp_path) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.wav", hash="abc", duration=100.0)
    keeper_id = _file(conn, tmp_path / "b.wav", hash="abc", duration=240.0)

    result = dedupe.find_duplicates(conn)

    assert next(m for m in result.groups[0].members if m.is_keeper).file_id == keeper_id
    conn.close()


def test_no_group_when_hash_is_null(tmp_path) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3")
    _file(conn, tmp_path / "b.mp3")

    assert dedupe.find_duplicates(conn).groups == ()
    conn.close()


def test_missing_files_are_excluded(tmp_path) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="abc")
    _file(conn, tmp_path / "b.mp3", hash="abc", is_missing=1)

    assert dedupe.find_duplicates(conn).groups == ()
    conn.close()


def test_isrc_groups_across_namespaces(tmp_path) -> None:
    conn = _catalog(tmp_path)
    a = _file(conn, tmp_path / "a.mp3", hash="h1")
    b = _file(conn, tmp_path / "b.mp3", hash="h2")
    _tag(conn, a, "TSRC", "US1234567890")
    _tag(conn, b, "isrc", "us1234567890")

    result = dedupe.find_duplicates(conn)

    assert [g.kind for g in result.groups] == ["isrc"]
    assert len(result.groups[0].members) == 2
    conn.close()


def test_mbid_groups_from_ufid_and_vorbis(tmp_path) -> None:
    conn = _catalog(tmp_path)
    a = _file(conn, tmp_path / "a.mp3", hash="h1")
    b = _file(conn, tmp_path / "b.flac", hash="h2")
    _tag(conn, a, "UFID:http://musicbrainz.org", "ABC-123")
    _tag(conn, b, "musicbrainz_trackid", "abc-123")

    result = dedupe.find_duplicates(conn)

    assert [g.kind for g in result.groups] == ["mbid"]
    conn.close()


def test_fingerprint_requires_flag(tmp_path) -> None:
    conn = _catalog(tmp_path)
    a = _file(conn, tmp_path / "a.mp3", hash="h1")
    b = _file(conn, tmp_path / "b.mp3", hash="h2")
    _fingerprint(conn, a, "FP")
    _fingerprint(conn, b, "FP")

    assert dedupe.find_duplicates(conn).groups == ()
    result = dedupe.find_duplicates(conn, use_fingerprint=True)
    assert [g.kind for g in result.groups] == ["fingerprint"]
    conn.close()


def test_find_duplicates_replaces_previous_groups(tmp_path) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="abc")
    _file(conn, tmp_path / "b.mp3", hash="abc")
    dedupe.find_duplicates(conn)

    _file(conn, tmp_path / "c.mp3", hash="xyz")
    _file(conn, tmp_path / "d.mp3", hash="xyz")
    result = dedupe.find_duplicates(conn)

    assert len(result.groups) == 2
    assert conn.execute("SELECT COUNT(*) FROM dup_groups").fetchone()[0] == 2
    conn.close()


def test_compute_fingerprints_stores_results(tmp_path, monkeypatch) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="h1")
    monkeypatch.setattr(dedupe, "_load_acoustid", lambda: object())
    monkeypatch.setattr(dedupe, "fingerprint_file", lambda path: (12.0, "FP123"))

    computed, errors = dedupe.compute_fingerprints(conn)

    assert (computed, errors) == (1, 0)
    row = conn.execute("SELECT fingerprint, duration FROM fingerprints").fetchone()
    assert (row["fingerprint"], row["duration"]) == ("FP123", 12.0)
    conn.close()


def test_compute_fingerprints_raises_when_unavailable(tmp_path, monkeypatch) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="h1")

    def boom() -> object:
        raise dedupe.FingerprintUnavailable("sem chromaprint")

    monkeypatch.setattr(dedupe, "_load_acoustid", boom)

    with pytest.raises(dedupe.FingerprintUnavailable):
        dedupe.compute_fingerprints(conn)
    conn.close()


def test_compute_fingerprints_records_errors(tmp_path, monkeypatch) -> None:
    conn = _catalog(tmp_path)
    _file(conn, tmp_path / "a.mp3", hash="h1")
    monkeypatch.setattr(dedupe, "_load_acoustid", lambda: object())

    def fail(path: Path) -> tuple[float, str]:
        raise ValueError("arquivo invalido")

    monkeypatch.setattr(dedupe, "fingerprint_file", fail)

    computed, errors = dedupe.compute_fingerprints(conn)

    assert (computed, errors) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM scan_errors").fetchone()[0] == 1
    conn.close()
