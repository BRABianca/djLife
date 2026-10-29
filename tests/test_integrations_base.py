import pytest

from djlife import db
from djlife.integrations import base


def _track(ref_id: str, stored: str, *, exists: bool, software: str = base.SOFTWARE_SERATO):
    return base.DjTrack(
        software=software,
        ref_id=ref_id,
        stored=stored,
        path=stored,
        title=None,
        artist=None,
        exists=exists,
    )


def _journal(conn, op: str, strategy: str, src: str, dst: str, file_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO journal(batch, created_at, op, strategy, src, dst, file_id, undone)"
        " VALUES ('b', 'now', ?, ?, ?, ?, ?, 0)",
        (op, strategy, src, dst, file_id),
    )


def _insert_file(conn, path: str) -> int:
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES (?, 'wav', 1, 0.0, 'h', 0, 'now', 'now')",
        (path,),
    )
    return int(conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()["id"])


def test_backup_database_creates_copy(tmp_path) -> None:
    target = tmp_path / "master.sqlite"
    target.write_bytes(b"conteudo")

    backup = base.backup_database(target)

    assert backup != target
    assert backup.exists()
    assert backup.read_bytes() == b"conteudo"


def test_backup_database_missing_raises(tmp_path) -> None:
    with pytest.raises(base.IntegrationUnavailable):
        base.backup_database(tmp_path / "inexistente.sqlite")


def test_integrity_report_counts() -> None:
    tracks = (_track("1", "/a.wav", exists=True), _track("2", "/b.wav", exists=False))

    report = base.integrity_report(base.SOFTWARE_SERATO, tracks)

    assert report.total == 2
    assert report.resolved == 1
    assert report.missing == 1
    assert report.samples == ("/b.wav",)
    assert not report.healthy


def test_resolve_move_mapping_plain_move(tmp_path) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    _journal(conn, "move", "move", str(tmp_path / "src.wav"), str(tmp_path / "dst.wav"))
    conn.commit()

    mapping = base.resolve_move_mapping(conn)

    assert mapping[base.norm(tmp_path / "src.wav")] == str(tmp_path / "dst.wav")
    conn.close()


def test_resolve_move_mapping_quarantine_points_to_keeper(tmp_path, make_wav) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    keeper = make_wav(tmp_path / "lib" / "a.wav")
    duplicate = make_wav(tmp_path / "lib" / "b.wav")
    keeper_id = _insert_file(conn, str(keeper))
    dup_id = _insert_file(conn, str(duplicate))
    conn.execute("INSERT INTO dup_groups(kind, key, created_at) VALUES ('hash', 'h', 'now')")
    group_id = int(conn.execute("SELECT id FROM dup_groups").fetchone()["id"])
    conn.execute(
        "INSERT INTO dup_members(group_id, file_id, is_keeper) VALUES (?, ?, 1)",
        (group_id, keeper_id),
    )
    conn.execute(
        "INSERT INTO dup_members(group_id, file_id, is_keeper) VALUES (?, ?, 0)",
        (group_id, dup_id),
    )
    _journal(conn, "move", "quarantine", str(duplicate), str(tmp_path / "q" / "b.wav"), dup_id)
    conn.commit()

    mapping = base.resolve_move_mapping(conn)

    assert mapping[base.norm(duplicate)] == str(keeper)
    conn.close()


def test_resolve_move_mapping_ignores_undone(tmp_path) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    _journal(conn, "move", "move", str(tmp_path / "src.wav"), str(tmp_path / "dst.wav"))
    conn.execute("UPDATE journal SET undone = 1")
    conn.commit()

    assert base.resolve_move_mapping(conn) == {}
    conn.close()


def test_relink_plan_only_missing_and_mapped() -> None:
    tracks = (
        _track("1", "/lib/a.wav", exists=True),
        _track("2", "/lib/b.wav", exists=False),
        _track("3", "/lib/c.wav", exists=False),
    )
    mapping = {base.norm("/lib/b.wav"): "/out/b.wav"}

    plan = base.relink_plan("serato", tracks, mapping, convert=lambda new, old: new)

    assert plan.count == 1
    assert plan.changes[0].ref_id == "2"
    assert plan.changes[0].old == "/lib/b.wav"
    assert plan.changes[0].new == "/out/b.wav"


def test_relink_plan_dedupes_by_path() -> None:
    tracks = (_track("1", "/lib/a.wav", exists=False), _track("2", "/lib/a.wav", exists=False))
    mapping = {base.norm("/lib/a.wav"): "/out/a.wav"}

    plan = base.relink_plan("serato", tracks, mapping, convert=lambda new, old: new)

    assert plan.count == 1


def test_relink_plan_skips_unchanged_target() -> None:
    tracks = (_track("1", "/lib/a.wav", exists=False),)
    mapping = {base.norm("/lib/a.wav"): "/lib/a.wav"}

    plan = base.relink_plan("serato", tracks, mapping, convert=lambda new, old: old)

    assert plan.count == 0
