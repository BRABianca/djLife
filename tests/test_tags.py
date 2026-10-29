from typing import Any

import pytest
from mutagen import MutagenError
from mutagen.id3 import ID3, TALB, TBPM, TIT2, TPE1, TXXX
from mutagen.mp4 import MP4Tags

from djlife import db, tags


def test_id3_extraction():
    id3 = ID3()
    id3.add(TIT2(encoding=3, text="Titulo"))
    id3.add(TPE1(encoding=3, text="Artista"))
    id3.add(TALB(encoding=3, text="Album"))
    id3.add(TBPM(encoding=3, text="128"))
    id3.add(TXXX(encoding=3, desc="DJLIFE_ENERGY", text="7"))

    entries, summary = tags._id3(id3)
    data = dict(entries)
    assert summary == {"title": "Titulo", "artist": "Artista", "album": "Album"}
    assert data["TBPM"] == "128"
    assert data["TXXX:DJLIFE_ENERGY"] == "7"


def test_mp4_extraction():
    mp4 = MP4Tags()
    mp4["\xa9nam"] = ["Titulo"]
    mp4["\xa9ART"] = ["Artista"]
    mp4["tmpo"] = [128]

    entries, summary = tags._mp4(mp4)
    data = dict(entries)
    assert summary["title"] == "Titulo"
    assert data["\xa9ART"] == "Artista"
    assert data["tmpo"] == "128"


def test_vorbis_extraction():
    vorbis: dict[str, Any] = {"title": ["T"], "artist": ["A"], "bpm": ["124"]}
    entries, summary = tags._vorbis(vorbis)
    data = dict(entries)
    assert summary["title"] == "T"
    assert data["bpm"] == "124"


def test_read_tags_raises_on_corrupt_file(tmp_path):
    path = tmp_path / "garbage.mp3"
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(MutagenError):
        tags.read_tags(path)


def test_read_tags_on_untagged_file(make_wav, tmp_path):
    path = make_wav(tmp_path / "a.wav")
    data = tags.read_tags(path)
    assert data.entries == ()
    assert data.duration is not None


def _insert_file(conn, path, size=2):
    conn.execute(
        """INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
        (str(path), path.suffix.lstrip("."), size, 0.0, None, "now", "now"),
    )
    conn.commit()


def test_index_tags_creates_track(make_wav, tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    path = make_wav(tmp_path / "a.wav")
    _insert_file(conn, path, size=path.stat().st_size)

    indexed, errors = tags.index_tags(conn)
    assert (indexed, errors) == (1, 0)
    assert conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    conn.close()


def test_index_tags_is_idempotent(make_wav, tmp_path):
    conn = db.open_catalog(tmp_path / "catalog.db")
    path = make_wav(tmp_path / "a.wav")
    _insert_file(conn, path, size=path.stat().st_size)

    tags.index_tags(conn)
    tags.index_tags(conn)
    assert conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    conn.close()
