from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "djlife"
SCHEMA_VERSION = 3


def default_db_path() -> Path:
    return Path(user_data_dir(APP_NAME)) / "catalog.db"


def _schema_sql() -> str:
    return Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def connect(db_path: Path | str, *, create: bool = True) -> sqlite3.Connection:
    path = Path(db_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0


def initialize(conn: sqlite3.Connection) -> int:
    conn.executescript(_schema_sql())
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('taxonomy_version', '0.0.0')"
    )
    conn.commit()
    return schema_version(conn)


def open_catalog(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(Path(db_path) if db_path else default_db_path())
    initialize(conn)
    return conn
