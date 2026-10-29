PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS genres (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES genres(id) ON DELETE CASCADE,
    level       INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    replaced_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_genres_parent ON genres(parent_id);

CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    ext        TEXT NOT NULL,
    size       INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    hash       TEXT,
    is_missing INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_missing ON files(is_missing);

CREATE TABLE IF NOT EXISTS tracks (
    id         INTEGER PRIMARY KEY,
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    title      TEXT,
    artist     TEXT,
    album      TEXT,
    duration   REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_file ON tracks(file_id);

CREATE TABLE IF NOT EXISTS tags (
    id        INTEGER PRIMARY KEY,
    file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL DEFAULT '',
    key       TEXT NOT NULL,
    value     TEXT,
    UNIQUE (file_id, namespace, key)
);

CREATE TABLE IF NOT EXISTS audio_analysis (
    id               INTEGER PRIMARY KEY,
    file_id          INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    analyzer         TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    bpm              REAL,
    key_camelot      TEXT,
    key_open         TEXT,
    energy           REAL,
    danceability     REAL,
    loudness_lufs    REAL,
    analyzed_at      TEXT NOT NULL,
    UNIQUE (file_id, analyzer, analysis_version)
);

CREATE TABLE IF NOT EXISTS track_genres (
    id         INTEGER PRIMARY KEY,
    track_id   INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    genre_id   INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'C',
    score      REAL,
    created_at TEXT NOT NULL,
    UNIQUE (track_id, genre_id, source)
);
CREATE INDEX IF NOT EXISTS idx_track_genres_track ON track_genres(track_id);

CREATE TABLE IF NOT EXISTS scan_runs (
    id            INTEGER PRIMARY KEY,
    root          TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    files_seen    INTEGER NOT NULL DEFAULT 0,
    files_new     INTEGER NOT NULL DEFAULT 0,
    files_updated INTEGER NOT NULL DEFAULT 0,
    files_missing INTEGER NOT NULL DEFAULT 0,
    errors        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_errors (
    id      INTEGER PRIMARY KEY,
    run_id  INTEGER REFERENCES scan_runs(id) ON DELETE CASCADE,
    path    TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_errors_run ON scan_errors(run_id);

CREATE TABLE IF NOT EXISTS journal (
    id         INTEGER PRIMARY KEY,
    batch      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    op         TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    src        TEXT NOT NULL,
    dst        TEXT,
    file_id    INTEGER REFERENCES files(id) ON DELETE SET NULL,
    undone     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_journal_batch ON journal(batch);
CREATE INDEX IF NOT EXISTS idx_journal_undone ON journal(undone);

CREATE TABLE IF NOT EXISTS fingerprints (
    file_id     INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    duration    REAL,
    source      TEXT NOT NULL DEFAULT 'chromaprint',
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fingerprints_value ON fingerprints(fingerprint);

CREATE TABLE IF NOT EXISTS dup_groups (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (kind, key)
);

CREATE TABLE IF NOT EXISTS dup_members (
    group_id  INTEGER NOT NULL REFERENCES dup_groups(id) ON DELETE CASCADE,
    file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    is_keeper INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_dup_members_file ON dup_members(file_id);

CREATE TABLE IF NOT EXISTS file_versions (
    file_id    INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    version    TEXT NOT NULL,
    source     TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'C',
    updated_at TEXT NOT NULL
);
