import sqlite3
from pathlib import Path

import pytest

from djlife.integrations import serato
from djlife.integrations.base import IntegrationUnavailable, norm, relink_plan


def _make_db(path: Path, columns: str = "portable_id TEXT, file_name TEXT, artist TEXT") -> None:
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE asset ({columns})")
    conn.commit()
    conn.close()


def _insert(path: Path, value: str, name: str | None, artist: str | None) -> None:
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO asset VALUES (?, ?, ?)", (value, name, artist))
    conn.commit()
    conn.close()


def test_read_tracks_absolute_and_relative(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    present = make_wav(library / "a.wav")
    db_path = tmp_path / "master.sqlite"
    _make_db(db_path)
    _insert(db_path, str(present), "a.wav", "Artista A")
    _insert(db_path, "b.wav", "b.wav", "Artista B")

    tracks = serato.read_tracks(db_path, roots=(library,))

    assert len(tracks) == 2
    assert tracks[0].path == str(present)
    assert tracks[0].exists is True
    assert tracks[0].title == "a.wav"
    assert tracks[0].artist == "Artista A"
    assert tracks[1].path == str(library / "b.wav")
    assert tracks[1].exists is False


def test_status_reports_missing(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    db_path = tmp_path / "master.sqlite"
    _make_db(db_path)
    _insert(db_path, str(library / "a.wav"), "a.wav", None)
    _insert(db_path, str(library / "gone.wav"), "gone.wav", None)

    report = serato.status(db_path, roots=(library,))

    assert report.total == 2
    assert report.resolved == 1
    assert report.missing == 1


def test_missing_database_raises(tmp_path) -> None:
    with pytest.raises(IntegrationUnavailable):
        serato.read_tracks(tmp_path / "nope.sqlite")


def test_missing_path_column_raises(tmp_path) -> None:
    db_path = tmp_path / "master.sqlite"
    _make_db(db_path, columns="foo TEXT, bar TEXT")

    with pytest.raises(IntegrationUnavailable):
        serato.read_tracks(db_path)


def test_relink_updates_path_name_and_backs_up(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    original = make_wav(library / "a.wav")
    db_path = tmp_path / "master.sqlite"
    _make_db(db_path)
    _insert(db_path, str(original), "a.wav", "Artista A")

    moved = tmp_path / "moved" / "b.wav"
    moved.parent.mkdir(parents=True)
    original.rename(moved)

    tracks = serato.read_tracks(db_path, roots=(library,))
    mapping = {norm(original): str(moved)}
    plan = relink_plan(
        serato.SOFTWARE_SERATO,
        tracks,
        mapping,
        convert=lambda new, old: serato.to_stored(new, old, (library,)),
    )
    assert plan.count == 1

    result = serato.relink(db_path, plan, roots=(library,), apply=True)

    assert result.applied == 1
    assert result.errors == 0
    assert result.backup is not None and result.backup.exists()
    assert result.after is not None and result.after.healthy

    conn = sqlite3.connect(db_path)
    stored, name = conn.execute("SELECT portable_id, file_name FROM asset").fetchone()
    conn.close()
    assert stored == str(moved)
    assert name == "b.wav"


def test_relink_dry_run_does_not_touch(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    original = make_wav(library / "a.wav")
    db_path = tmp_path / "master.sqlite"
    _make_db(db_path)
    _insert(db_path, str(original), "a.wav", None)

    tracks = serato.read_tracks(db_path, roots=(library,))
    mapping = {norm(original): str(tmp_path / "moved" / "a.wav")}
    plan = relink_plan(serato.SOFTWARE_SERATO, tracks, mapping, convert=lambda new, old: new)

    result = serato.relink(db_path, plan, roots=(library,), apply=False)

    assert result.applied == 0
    assert result.backup is None
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT portable_id FROM asset").fetchone()[0] == str(original)
    conn.close()


def test_to_stored_relative_when_original_relative(tmp_path) -> None:
    roots = (tmp_path,)
    new_abs = str(tmp_path / "a" / "b.wav")

    assert serato.to_stored(new_abs, "a/b.wav", roots) == "a/b.wav"


def test_to_stored_keeps_absolute_when_original_absolute(tmp_path) -> None:
    new_abs = str(tmp_path / "a" / "b.wav")
    original_abs = str(tmp_path / "lib" / "a.wav")

    assert serato.to_stored(new_abs, original_abs, (tmp_path,)) == new_abs
