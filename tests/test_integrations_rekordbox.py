import sys
import types
from types import SimpleNamespace

import pytest

from djlife.integrations import rekordbox
from djlife.integrations.base import (
    SOFTWARE_REKORDBOX,
    IntegrationUnavailable,
    RelinkChange,
    RelinkPlan,
)


class _FakeContent:
    def __init__(self, cid, folder, name, title, artist):
        self.ID = cid
        self.FolderPath = folder
        self.FileNameL = name
        self.Title = title
        self.Artist = SimpleNamespace(Name=artist)


class _FakeDb:
    def __init__(self, contents):
        self._contents = list(contents)
        self.committed = False

    def get_content(self):
        return list(self._contents)

    def commit(self):
        self.committed = True


def _install(monkeypatch, contents):
    database = _FakeDb(contents)
    module = types.ModuleType("pyrekordbox")
    module.Rekordbox6Database = lambda path=None: database
    monkeypatch.setitem(sys.modules, "pyrekordbox", module)
    return database


def _plan(old, new, ref_id="7"):
    return RelinkPlan(
        software=SOFTWARE_REKORDBOX,
        changes=(RelinkChange(ref_id=ref_id, old=old, new=new),),
    )


def test_missing_dependency_raises(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyrekordbox", None)

    with pytest.raises(IntegrationUnavailable):
        rekordbox.read_tracks()


def test_read_tracks_resolves_folder_and_file(tmp_path, monkeypatch) -> None:
    present = tmp_path / "a.flac"
    present.write_bytes(b"x")
    contents = [
        _FakeContent(1, str(tmp_path), "a.flac", "Faixa A", "Artista A"),
        _FakeContent(2, str(tmp_path / "gone.flac"), None, "Faixa B", None),
    ]
    _install(monkeypatch, contents)

    tracks = rekordbox.read_tracks()

    assert len(tracks) == 2
    assert tracks[0].path == str(present)
    assert tracks[0].exists is True
    assert tracks[0].title == "Faixa A"
    assert tracks[0].artist == "Artista A"
    assert tracks[1].path == str(tmp_path / "gone.flac")
    assert tracks[1].exists is False


def test_read_tracks_with_explicit_db_path(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"sqlcipher")
    seen = []
    database = _FakeDb((_FakeContent(1, str(tmp_path / "a.flac"), None, None, None),))
    module = types.ModuleType("pyrekordbox")

    def _factory(path=None):
        seen.append(path)
        return database

    module.Rekordbox6Database = _factory
    monkeypatch.setitem(sys.modules, "pyrekordbox", module)

    rekordbox.read_tracks(db_file)

    assert seen == [str(db_file)]


def test_content_without_folder_is_skipped(tmp_path, monkeypatch) -> None:
    _install(monkeypatch, [_FakeContent(1, None, "a.flac", "T", "A")])

    assert rekordbox.read_tracks() == ()


def test_relink_writes_backup_and_updates(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"sqlcipher")
    original = tmp_path / "old.flac"
    target = tmp_path / "moved" / "new.flac"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    content = _FakeContent(7, str(original), "old.flac", "T", "A")
    database = _install(monkeypatch, [content])

    result = rekordbox.relink(db_file, _plan(str(original), str(target)), apply=True)

    assert result.applied == 1
    assert result.errors == 0
    assert result.backup is not None and result.backup.exists()
    assert result.after is not None and result.after.healthy
    assert content.FolderPath == str(target)
    assert content.FileNameL == "new.flac"
    assert database.committed is True


def test_relink_dry_run_does_not_touch(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"sqlcipher")
    old = tmp_path / "old.flac"
    content = _FakeContent(7, str(old), "old.flac", "T", "A")
    database = _install(monkeypatch, [content])

    result = rekordbox.relink(db_file, _plan(str(old), str(tmp_path / "new.flac")), apply=False)

    assert result.applied == 0
    assert result.backup is None
    assert content.FolderPath == str(old)
    assert database.committed is False


def test_to_stored_preserves_separator() -> None:
    assert rekordbox.to_stored("C:\\x\\y.flac", "C:/x/y.flac") == "C:/x/y.flac"
    assert rekordbox.to_stored("C:\\x\\y.flac", "C:\\x\\y.flac") == "C:\\x\\y.flac"


def test_relink_without_changes_returns_zero(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"sqlcipher")
    _install(monkeypatch, [_FakeContent(1, str(tmp_path / "a.flac"), None, None, None)])
    plan = RelinkPlan(software=SOFTWARE_REKORDBOX, changes=())

    result = rekordbox.relink(db_file, plan, apply=True)

    assert result.applied == 0
    assert result.backup is None
