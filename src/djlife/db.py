from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "djlife"
SCHEMA_VERSION = 5


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
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0


def _stamp_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def initialize(conn: sqlite3.Connection) -> int:
    conn.executescript(_schema_sql())
    _stamp_version(conn)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('taxonomy_version', '0.0.0')")
    conn.commit()
    return schema_version(conn)


def migrate(conn: sqlite3.Connection) -> int:
    """Migra o schema incrementalmente ate ``SCHEMA_VERSION`` (idempotente).

    Banco vazio (versao 0) e inicializado por completo; bancos antigos recebem apenas os
    passos pendentes. Cada passo e seguro para reexecucao. Devolve a versao final.
    """
    current = schema_version(conn)
    if current >= SCHEMA_VERSION:
        return current
    if current == 0:
        return initialize(conn)
    conn.executescript(_schema_sql())
    if current < 5:
        _add_column(conn, "track_genres", "model_version", "TEXT")
    _stamp_version(conn)
    conn.commit()
    return schema_version(conn)


def open_catalog(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(Path(db_path) if db_path else default_db_path())
    migrate(conn)
    return conn
