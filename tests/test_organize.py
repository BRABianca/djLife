import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from djlife import db, taxonomy
from djlife.config import (
    CatalogConfig,
    ClassificationConfig,
    Config,
    FilesConfig,
    LicenseConfig,
)
from djlife.ui import organize, server

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

ADMIN_TOKEN = "segredo"


def _get(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read()


def _post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read()


def _seed(tmp_path, make_wav, *, slug: str | None = "house.deep_house"):
    db_path = tmp_path / "catalog.db"
    conn = db.open_catalog(db_path)
    source = tmp_path / "genres.yaml"
    source.write_text(TAXONOMY_YAML, encoding="utf-8")
    taxonomy.sync(conn, taxonomy.load_taxonomy(source))
    src = make_wav(tmp_path / "in" / "a.wav")
    conn.execute(
        "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, NULL, 0, 'now', 'now')",
        (str(src), "wav", 2, 0.0),
    )
    file_id = int(conn.execute("SELECT MAX(id) AS id FROM files").fetchone()["id"])
    conn.execute(
        "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
        " VALUES (?, ?, ?, NULL, NULL, 'now')",
        (file_id, "Groove", "DJ X"),
    )
    track_id = int(conn.execute("SELECT MAX(id) AS id FROM tracks").fetchone()["id"])
    if slug is not None:
        conn.execute(
            "INSERT INTO track_genres(track_id, genre_id, source, confidence, score, created_at)"
            " VALUES (?, (SELECT id FROM genres WHERE slug = ?), 'tags', 'A', NULL, 'now')",
            (track_id, slug),
        )
    conn.commit()
    conn.close()
    return db_path, src, track_id


def _config(tmp_path, db_path: Path, *, target: Path | None = None) -> Config:
    return Config(
        catalog=CatalogConfig(path=db_path),
        classification=ClassificationConfig(taxonomy=str(tmp_path / "genres.yaml")),
        files=FilesConfig(target=target if target is not None else tmp_path / "out"),
        license=LicenseConfig(admin_token=ADMIN_TOKEN),
    )


def _wait(job, timeout: float = 10.0):
    deadline = time.time() + timeout
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.05)
    return job


def test_status_reports_configuration(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    cfg = _config(tmp_path, db_path)

    status = organize.status(cfg)

    assert status["configured"] is False
    assert status["strategy"] == "hardlink"
    assert status["target"] == str(tmp_path / "out")
    assert status["catalog_exists"] is True
    assert "hardlink" in status["strategies"]


def test_plan_payload_lists_ready_items(tmp_path, make_wav) -> None:
    db_path, src, track_id = _seed(tmp_path, make_wav)
    cfg = _config(tmp_path, db_path)

    payload = organize.plan_payload(cfg)

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["ready"] == 1
    item = payload["items"][0]
    assert item["track_id"] == track_id
    assert item["status"] == "ready"
    assert item["genre"] == "House"
    assert item["subgenre"] == "Deep House"
    assert item["src"] == str(src)
    assert item["dst"].endswith("House\\Deep House\\DJ X - Groove.wav") or item["dst"].endswith(
        "House/Deep House/DJ X - Groove.wav"
    )


def test_plan_payload_requires_target(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    cfg = Config(catalog=CatalogConfig(path=db_path), files=FilesConfig(target=None))

    with pytest.raises(organize.OrganizeError):
        organize.plan_payload(cfg)


def test_plan_payload_requires_catalog(tmp_path) -> None:
    cfg = Config(catalog=CatalogConfig(path=tmp_path / "missing.db"), files=FilesConfig())

    with pytest.raises(organize.OrganizeError):
        organize.plan_payload(cfg)


def test_classify_job_runs(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    cfg = _config(tmp_path, db_path)

    job = _wait(organize.start_classify(cfg))

    assert job.status == "done"
    assert job.result["tracks"] == 1
    assert job.result["genres"] >= 2
    assert job.result["taxonomy_version"] == "9.9.9"


def test_apply_and_undo_round_trip(tmp_path, make_wav) -> None:
    db_path, src, _ = _seed(tmp_path, make_wav)
    target = tmp_path / "out"
    cfg = _config(tmp_path, db_path, target=target)

    applied = _wait(organize.start_apply(cfg))
    assert applied.status == "done"
    assert applied.result["linked"] == 1
    assert applied.result["tagged"] == 1
    dst = target / "House" / "Deep House" / "DJ X - Groove.wav"
    assert dst.exists()

    history = organize.history(cfg)
    assert history["total"] == 1
    batch = history["batches"][0]["batch"]
    assert history["batches"][0]["pending"] == 2

    undone = _wait(organize.start_undo(cfg, batch=batch))
    assert undone.status == "done"
    assert undone.result["removed"] == 1
    assert not dst.exists()
    assert src.exists()
    assert organize.history(cfg)["batches"][0]["pending"] == 0


def test_apply_only_selected_tracks(tmp_path, make_wav) -> None:
    db_path, _, track_id = _seed(tmp_path, make_wav)
    cfg = _config(tmp_path, db_path)

    job = _wait(organize.start_apply(cfg, track_ids=[track_id + 999]))

    assert job.status == "done"
    assert job.result["requested"] == 0
    assert job.result["linked"] == 0


def _serve(cfg: Config, config_path: Path):
    httpd = server.build_server(cfg, host="127.0.0.1", port=0, config_path=config_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, thread, f"http://{host}:{port}"


def test_server_organize_reads(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    config_file = tmp_path / "djlife.toml"
    cfg = _config(tmp_path, db_path)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        _, body = _get(f"{base}/api/organize/status")
        assert json.loads(body)["strategy"] == "hardlink"

        _, body = _get(f"{base}/api/organize/plan")
        assert json.loads(body)["summary"]["ready"] == 1

        _, body = _get(f"{base}/api/organize/history")
        assert json.loads(body)["total"] == 0

        _, body = _get(f"{base}/api/organize/job?task=apply")
        assert json.loads(body)["status"] == "idle"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_organize_requires_token(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    config_file = tmp_path / "djlife.toml"
    cfg = _config(tmp_path, db_path)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/organize/scan", {})
        assert error.value.code == 403

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/organize/scan", {}, {"X-Admin-Token": "errado"})
        assert error.value.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_organize_apply_with_token(tmp_path, make_wav) -> None:
    db_path, _, _ = _seed(tmp_path, make_wav)
    config_file = tmp_path / "djlife.toml"
    target = tmp_path / "out"
    cfg = _config(tmp_path, db_path, target=target)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        headers = {"X-Admin-Token": ADMIN_TOKEN}
        _, body = _post(f"{base}/api/organize/apply", {}, headers)
        assert json.loads(body)["status"] in {"running", "done"}

        payload = {"status": "running"}
        for _ in range(60):
            _, body = _get(f"{base}/api/organize/job?task=apply")
            payload = json.loads(body)
            if payload["status"] != "running":
                break
            time.sleep(0.1)
        assert payload["status"] == "done"
        assert payload["result"]["linked"] == 1

        _, body = _get(f"{base}/api/organize/history")
        assert json.loads(body)["total"] == 1

        _, body = _get(f"{base}/api/organize/plan")
        assert json.loads(body)["summary"]["exists"] == 1

        query = urllib.parse.urlencode({"task": "apply"})
        _, body = _get(f"{base}/api/organize/job?{query}")
        assert json.loads(body)["result"]["tagged"] == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
