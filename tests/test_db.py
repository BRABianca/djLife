import sqlite3

import pytest

from djlife import db

EXPECTED_TABLES = {
    "meta",
    "genres",
    "files",
    "tracks",
    "tags",
    "audio_analysis",
    "track_genres",
    "scan_runs",
    "scan_errors",
}


def test_initialize_creates_tables(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    assert db.initialize(conn) == db.SCHEMA_VERSION
    names = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert names >= EXPECTED_TABLES
    conn.close()


def test_initialize_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    db.initialize(conn)
    db.initialize(conn)
    assert db.schema_version(conn) == db.SCHEMA_VERSION
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    db.initialize(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tags(file_id, key, value) VALUES (999, 'x', 'y')")
    conn.close()


def test_open_catalog_uses_wal(tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()
