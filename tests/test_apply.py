import os
from pathlib import Path

import pytest

from djlife import apply as apply_mod
from djlife import db, planner, tags, taxonomy

TAXONOMY_YAML = """
version: "9.9.9"
genres:
  - slug: house
    name: House
    children:
      - slug: house.deep_house
        name: Deep House
  - slug: techno
    name: Techno
"""

TEMPLATE = "{genre}/{subgenre}/{artist} - {title}"


def _catalog(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    source = tmp_path / "genres.yaml"
    source.write_text(TAXONOMY_YAML, encoding="utf-8")
    taxonomy.sync(conn, taxonomy.load_taxonomy(source))
    return conn


def _add_track(conn, path: Path, *, title: str, artist: str, slug: str | None) -> None:
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, NULL, 0, 'now', 'now')",
        (str(path), path.suffix.lstrip("."), 2, 0.0),
    )
    file_id = int(conn.execute("SELECT MAX(id) AS id FROM files").fetchone()["id"])
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (?, ?, ?, NULL, NULL, 'now')",
        (file_id, title, artist),
    )
    track_id = int(conn.execute("SELECT MAX(id) AS id FROM tracks").fetchone()["id"])
    if slug is not None:
        conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
            " VALUES (?, (SELECT id FROM genres WHERE slug = ?), 'tags', 'A', NULL, 'now')",
            (track_id, slug),
        )
    conn.commit()


def _prepare(tmp_path, make_wav, slug: str | None = "house.deep_house"):
    conn = _catalog(tmp_path)
    src = make_wav(tmp_path / "in" / "a.wav")
    _add_track(conn, src, title="Groove", artist="DJ X", slug=slug)
    return conn, src


def _plan(conn, target: Path, strategy: str = "hardlink") -> planner.Plan:
    return planner.build_plan(
        conn,
        target=target,
        template=TEMPLATE,
        unknown_dir=planner.DEFAULT_UNKNOWN_DIR,
        strategy=strategy,
    )


def test_apply_hardlink_links_and_journals(tmp_path, make_wav) -> None:
    conn, src = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"

    result = apply_mod.apply(conn, _plan(conn, target))
    dst = target / "House" / "Deep House" / "DJ X - Groove.wav"

    assert result.linked == 1
    assert result.tagged == 1
    assert dst.exists()
    assert os.stat(src).st_ino == os.stat(dst).st_ino
    assert conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 2
    conn.close()


def test_apply_writes_djlife_tags(tmp_path, make_wav) -> None:
    conn, _ = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"
    apply_mod.apply(conn, _plan(conn, target))

    data = tags.read_tags(target / "House" / "Deep House" / "DJ X - Groove.wav")
    entries = dict(data.entries)
    assert entries["TXXX:DJLIFE_GENRE"] == "House"
    assert entries["TXXX:DJLIFE_SUBGENRE"] == "Deep House"
    assert entries["TXXX:DJLIFE_TAXONOMY_VERSION"] == "9.9.9"
    conn.close()


def test_apply_tag_only_leaves_files_in_place(tmp_path, make_wav) -> None:
    conn, src = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"

    result = apply_mod.apply(conn, _plan(conn, target, strategy="tag_only"))

    assert result.linked == 0
    assert result.tagged == 1
    assert src.exists()
    assert not target.exists()
    assert dict(tags.read_tags(src).entries)["TXXX:DJLIFE_GENRE"] == "House"
    conn.close()


def test_apply_skips_unclassified(tmp_path, make_wav) -> None:
    conn, _ = _prepare(tmp_path, make_wav, slug=None)

    result = apply_mod.apply(conn, _plan(conn, tmp_path / "out"))

    assert result.applied == 0
    assert result.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 0
    conn.close()


def test_apply_move_relinks_catalog(tmp_path, make_wav) -> None:
    conn, src = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"

    result = apply_mod.apply(conn, _plan(conn, target, strategy="move"), write_tags=False)
    dst = target / "House" / "Deep House" / "DJ X - Groove.wav"

    assert result.moved == 1
    assert not src.exists()
    assert dst.exists()
    assert conn.execute("SELECT path FROM files").fetchone()["path"] == str(dst)
    conn.close()


def test_undo_removes_links_without_residue(tmp_path, make_wav) -> None:
    conn, src = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"
    result = apply_mod.apply(conn, _plan(conn, target))

    undone = apply_mod.undo(conn, result.batch, stop=target)

    assert undone.removed == 1
    assert undone.untagged == 1
    assert not (target / "House").exists()
    assert target.exists()
    assert src.exists()
    assert "TXXX:DJLIFE_GENRE" not in dict(tags.read_tags(src).entries)
    assert conn.execute("SELECT COUNT(*) FROM journal WHERE undone = 0").fetchone()[0] == 0
    conn.close()


def test_undo_restores_moved_files(tmp_path, make_wav) -> None:
    conn, src = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"
    result = apply_mod.apply(conn, _plan(conn, target, strategy="move"), write_tags=False)

    undone = apply_mod.undo(conn, result.batch, stop=target)

    assert undone.restored == 1
    assert src.exists()
    assert not (target / "House").exists()
    assert conn.execute("SELECT path FROM files").fetchone()["path"] == str(src)
    conn.close()


def test_undo_without_batch_returns_empty(tmp_path, make_wav) -> None:
    conn, _ = _prepare(tmp_path, make_wav)

    undone = apply_mod.undo(conn)

    assert undone.batch is None
    conn.close()


def test_undo_uses_last_batch(tmp_path, make_wav) -> None:
    conn, _ = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"
    result = apply_mod.apply(conn, _plan(conn, target))

    undone = apply_mod.undo(conn, stop=target)

    assert undone.batch == result.batch
    conn.close()


@pytest.mark.parametrize("strategy", ["hardlink", "move", "tag_only"])
def test_apply_is_idempotent_across_strategies(tmp_path, make_wav, strategy) -> None:
    conn, _ = _prepare(tmp_path, make_wav)
    target = tmp_path / "out"
    plan = _plan(conn, target, strategy=strategy)

    first = apply_mod.apply(conn, plan)
    rebuilt = _plan(conn, target, strategy=strategy)
    second = apply_mod.apply(conn, rebuilt)

    assert first.applied >= 1
    if strategy == "tag_only":
        assert rebuilt.items[0].status == planner.STATUS_READY
        assert second.applied == 1
    else:
        assert rebuilt.items[0].status == planner.STATUS_EXISTS
        assert second.applied == 0
    conn.close()
