import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from djlife import config as config_mod
from djlife import curation as curation_core
from djlife import db, premium, taxonomy
from djlife import license as license_mod
from djlife.config import Config, LicenseConfig
from djlife.ui import curation, server

ADMIN_TOKEN = "segredo"

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
    children:
      - slug: techno.minimal
        name: Minimal
"""


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


def _serve(cfg: Config, config_file: Path):
    httpd = server.build_server(cfg, host="127.0.0.1", port=0, config_path=config_file)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, thread, f"http://{host}:{port}"


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _licensed_config(
    tmp_path: Path,
    *,
    features: tuple[str, ...] = (premium.ASSISTED_CURATION_FEATURE,),
    token: str | None = ADMIN_TOKEN,
) -> tuple[Config, Path, Path]:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    catalog = tmp_path / "catalog.db"
    license_mod.generate_keypair(private_key, public_key)
    license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-curadoria",
        plan="lifetime",
        features=features,
        machine_hash_value=license_mod.machine_hash(),
        expires_at=None,
    )
    token_line = f'admin_token = "{token}"\n' if token else ""
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(
        f'[catalog]\npath = "{catalog.as_posix()}"\n\n'
        f'[license]\npublic_key = "{public_key.as_posix()}"\n'
        f'license_file = "{license_file.as_posix()}"\n{token_line}',
        encoding="utf-8",
    )
    return config_mod.load_config(config_file), config_file, catalog


def _build_catalog(path: Path, tmp_path: Path) -> int:
    """Cria o catalogo com uma faixa em conflito (tags x rules) e devolve o track_id."""
    conn = db.open_catalog(path)
    try:
        source = tmp_path / "genres.yaml"
        source.write_text(TAXONOMY_YAML, encoding="utf-8")
        taxonomy.sync(conn, taxonomy.load_taxonomy(source))
        conn.execute(
            "INSERT INTO files(path, ext, size, mtime, hash, is_missing, first_seen, last_seen)"
            " VALUES (?, 'wav', 2, 0.0, NULL, 0, 'now', 'now')",
            (str(tmp_path / "a.wav"),),
        )
        file_id = int(conn.execute("SELECT MAX(id) AS id FROM files").fetchone()["id"])
        conn.execute(
            "INSERT INTO tracks(file_id, title, artist, album, duration, created_at)"
            " VALUES (?, 'Track', 'DJ', NULL, NULL, 'now')",
            (file_id,),
        )
        track_id = int(conn.execute("SELECT MAX(id) AS id FROM tracks").fetchone()["id"])
        for slug, source_name, confidence in (
            ("house.deep_house", "tags", "A"),
            ("techno.minimal", "rules", "B"),
        ):
            conn.execute(
                "INSERT INTO track_genres"
                "(track_id, genre_id, source, confidence, score, created_at)"
                " VALUES (?, (SELECT id FROM genres WHERE slug = ?), ?, ?, NULL, 'now')",
                (track_id, slug, source_name, confidence),
            )
        conn.commit()
    finally:
        conn.close()
    return track_id


def _genre_id(catalog: Path, slug: str) -> int:
    conn = db.open_catalog(catalog)
    try:
        row = conn.execute("SELECT id FROM genres WHERE slug = ?", (slug,)).fetchone()
    finally:
        conn.close()
    return int(row["id"])


def test_queue_payload_requires_license() -> None:
    payload = curation.queue_payload(Config(license=LicenseConfig()))

    assert payload["feature"] == premium.ASSISTED_CURATION_FEATURE
    assert payload["licensed"] is False
    assert payload["reason"]
    assert payload["items"] == []


def test_queue_payload_lists_conflicts(tmp_path) -> None:
    cfg, _, catalog = _licensed_config(tmp_path)
    _build_catalog(catalog, tmp_path)

    payload = curation.queue_payload(cfg)

    assert payload["licensed"] is True
    assert payload["ready"] is True
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["level"] == curation_core.LEVEL_DIVERGENTE
    assert item["suggestion"]["label"] == "House > Deep House"
    assert {signal["source"] for signal in item["signals"]} == {"tags", "rules"}
    labels = {choice["label"] for choice in payload["choices"]}
    assert {"House", "House > Deep House", "Techno > Minimal"} <= labels


def test_gate_is_per_feature(tmp_path) -> None:
    cfg, _, _ = _licensed_config(tmp_path, features=(premium.DOWNLOAD_FEATURE,))

    payload = curation.queue_payload(cfg)

    assert payload["licensed"] is False
    with pytest.raises(curation.CurationUnavailable):
        curation.decide(cfg, 1, 1)


def test_decide_records_manual_decision(tmp_path) -> None:
    cfg, _, catalog = _licensed_config(tmp_path)
    track_id = _build_catalog(catalog, tmp_path)
    genre = _genre_id(catalog, "techno.minimal")

    result = curation.decide(cfg, track_id, genre)

    assert result["track_id"] == track_id
    assert result["genre_id"] == genre
    assert result["pending"] == 0
    conn = db.open_catalog(catalog)
    try:
        row = conn.execute(
            "SELECT source, confidence FROM track_genres WHERE track_id = ? AND genre_id = ?",
            (track_id, genre),
        ).fetchone()
    finally:
        conn.close()
    assert row["source"] == "manual"
    assert row["confidence"] == "A"


def test_decide_rejects_invalid_input(tmp_path) -> None:
    cfg, _, catalog = _licensed_config(tmp_path)
    _build_catalog(catalog, tmp_path)

    with pytest.raises(curation.CurationError):
        curation.decide(cfg, "x", "y")
    with pytest.raises(curation.CurationError):
        curation.decide(cfg, 1, 999999)


def test_decide_requires_catalog(tmp_path) -> None:
    cfg, _, _ = _licensed_config(tmp_path)

    with pytest.raises(curation.CurationError):
        curation.decide(cfg, 1, 1)


def test_server_curation_queue_and_decide(tmp_path) -> None:
    cfg, config_file, catalog = _licensed_config(tmp_path)
    track_id = _build_catalog(catalog, tmp_path)
    genre = _genre_id(catalog, "techno.minimal")
    httpd, thread, base = _serve(cfg, config_file)
    try:
        _, body = _get(f"{base}/api/premium/curation")
        payload = json.loads(body)
        assert payload["licensed"] is True
        assert payload["total"] == 1

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/premium/curation", {"track_id": track_id, "genre_id": genre})
        assert error.value.code == 403

        _, body = _post(
            f"{base}/api/premium/curation",
            {"track_id": track_id, "genre_id": genre},
            {"X-Admin-Token": ADMIN_TOKEN},
        )
        assert json.loads(body)["pending"] == 0

        _, body = _get(f"{base}/api/premium/curation")
        assert json.loads(body)["total"] == 0
    finally:
        _stop(httpd, thread)


def test_server_curation_requires_license(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(f'[license]\nadmin_token = "{ADMIN_TOKEN}"\n', encoding="utf-8")
    cfg = config_mod.load_config(config_file)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        _, body = _get(f"{base}/api/premium/curation")
        assert json.loads(body)["licensed"] is False

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(
                f"{base}/api/premium/curation",
                {"track_id": 1, "genre_id": 1},
                {"X-Admin-Token": ADMIN_TOKEN},
            )
        assert error.value.code == 403
    finally:
        _stop(httpd, thread)


def test_server_curation_rejects_invalid_body(tmp_path) -> None:
    cfg, config_file, catalog = _licensed_config(tmp_path)
    _build_catalog(catalog, tmp_path)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _post(
                f"{base}/api/premium/curation",
                {"track_id": "x"},
                {"X-Admin-Token": ADMIN_TOKEN},
            )
        assert error.value.code == 400
    finally:
        _stop(httpd, thread)
