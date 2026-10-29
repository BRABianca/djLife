import pytest

from djlife import db, versions


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Track (Extended Mix)", "Extended"),
        ("Track (Radio Edit)", "Radio"),
        ("Track (Original Mix)", "Original"),
        ("Track (DJ Foo Remix)", "Remix"),
        ("Track (Frankie Rework)", "Remix"),
        ("Track (Bootleg)", "Bootleg"),
        ("Track (Instrumental)", "Instrumental"),
        ("Track (Accapella)", "Acapella"),
        ("Track (Dub Mix)", "Dub"),
        ("A vs B Mashup", "Mashup"),
        ("Just A Track", "Original"),
    ],
)
def test_classify_text(text: str, expected: str) -> None:
    assert versions.classify_text(text)[0] == expected


def test_classify_text_default_confidence() -> None:
    assert versions.classify_text("Plain Title") == ("Original", "C")


def test_classify_versions_writes_table(tmp_path) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES ('/x/a.wav', 'wav', 1, 0.0, NULL, 0, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (1, 'Track (Extended Mix)', NULL, NULL, NULL, 'now')"
    )
    conn.commit()

    result = versions.classify_versions(conn)

    assert result.tracks == 1
    assert result.classified == 1
    assert result.counts == (("Extended", 1),)
    row = conn.execute("SELECT version, confidence, source FROM file_versions").fetchone()
    assert (row["version"], row["confidence"], row["source"]) == ("Extended", "A", "rules")
    conn.close()


def test_classify_versions_is_idempotent(tmp_path) -> None:
    conn = db.open_catalog(tmp_path / "catalog.db")
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES ('/x/a.wav', 'wav', 1, 0.0, NULL, 0, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (1, 'Track', NULL, NULL, NULL, 'now')"
    )
    conn.commit()

    versions.classify_versions(conn)
    versions.classify_versions(conn)

    assert conn.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 1
    conn.close()
