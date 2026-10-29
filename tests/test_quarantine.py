import sqlite3
from pathlib import Path

from djlife import apply as apply_mod
from djlife import db, dedupe, quarantine


def _setup(tmp_path, make_wav) -> tuple[sqlite3.Connection, Path, Path]:
    conn = db.open_catalog(tmp_path / "catalog.db")
    keeper = make_wav(tmp_path / "lib" / "a.wav")
    duplicate = make_wav(tmp_path / "lib" / "sub" / "b.wav")
    for path in (keeper, duplicate):
        conn.execute(
            "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
            " VALUES (?, 'wav', ?, 0.0, 'dup', 0, 'now', 'now')",
            (str(path), path.stat().st_size),
        )
    conn.commit()
    dedupe.find_duplicates(conn)
    return conn, keeper, duplicate


def _file_id(conn, path: Path) -> int:
    return int(conn.execute("SELECT id FROM files WHERE path = ?", (str(path),)).fetchone()["id"])


def test_build_plan_excludes_keeper(tmp_path, make_wav) -> None:
    conn, keeper, duplicate = _setup(tmp_path, make_wav)

    plan = quarantine.build_quarantine_plan(conn, tmp_path / "q")

    assert plan.count == 1
    assert plan.items[0].file_id == _file_id(conn, duplicate)
    assert plan.items[0].src == duplicate
    assert plan.items[0].keeper == str(keeper)
    assert plan.bytes_reclaimable == duplicate.stat().st_size
    conn.close()


def test_apply_moves_and_undo_restores(tmp_path, make_wav) -> None:
    conn, _keeper, duplicate = _setup(tmp_path, make_wav)
    qroot = tmp_path / "q"
    plan = quarantine.build_quarantine_plan(conn, qroot)

    result = quarantine.apply_quarantine(conn, plan)

    moved = qroot / "hash" / "b.wav"
    assert result.moved == 1
    assert result.errors == 0
    assert not duplicate.exists()
    assert moved.exists()
    row = conn.execute("SELECT path FROM files WHERE id = ?", (plan.items[0].file_id,)).fetchone()
    assert row["path"] == str(moved)

    undone = apply_mod.undo(conn, result.batch, quarantine_dir=qroot)

    assert undone.restored == 1
    assert duplicate.exists()
    assert not moved.exists()
    assert not (qroot / "hash").exists()
    assert qroot.exists()
    row = conn.execute("SELECT path FROM files WHERE id = ?", (plan.items[0].file_id,)).fetchone()
    assert row["path"] == str(duplicate)
    conn.close()


def test_replan_after_apply_is_empty(tmp_path, make_wav) -> None:
    conn, _keeper, _duplicate = _setup(tmp_path, make_wav)
    qroot = tmp_path / "q"
    quarantine.apply_quarantine(conn, quarantine.build_quarantine_plan(conn, qroot))

    assert quarantine.build_quarantine_plan(conn, qroot).count == 0
    conn.close()


def test_plan_without_duplicates_is_empty(tmp_path, make_wav) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    make_wav(tmp_path / "lib" / "a.wav")

    assert quarantine.build_quarantine_plan(conn, tmp_path / "q").count == 0
    conn.close()
