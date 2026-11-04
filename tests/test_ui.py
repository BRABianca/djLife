import json
import threading
import urllib.error
import urllib.request

import pytest
from typer.testing import CliRunner

from djlife import config as config_mod
from djlife.cli import app
from djlife.ui import data, server

runner = CliRunner()


def _library(tmp_path, make_wav):
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    make_wav(library / "sub" / "b.wav")
    db_path = tmp_path / "catalog.db"
    qroot = tmp_path / "q"
    rules = tmp_path / "genres.local.yaml"
    rules.write_text(
        'version: "0.1.0"\nrules:\n'
        '  - name: lib\n    field: path\n    match: "lib"\n'
        "    genre: house\n    confidence: B\n",
        encoding="utf-8",
    )
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n'
        f'[classification]\nlocal_taxonomy = "{rules.as_posix()}"\n'
        f'[files]\nquarantine_dir = "{qroot.as_posix()}"\n',
        encoding="utf-8",
    )
    for command in ("scan", "classify", "duplicates", "versions"):
        assert runner.invoke(app, [command, "--config", str(config)]).exit_code == 0
    return config_mod.load_config(config)


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def test_overview_reports_catalog(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)

    payload = data.overview(cfg)

    assert payload["stats"]["files"] == 2
    assert payload["stats"]["tracks"] == 2
    assert payload["classification"]["classified"] >= 1
    assert payload["catalog"]["schema_version"] == "4"
    assert payload["duplicates"]["total"] >= 1
    assert payload["embeddings"]["files"] == 0


def test_tracks_search(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)

    rows = data.tracks(cfg, "a.wav")

    assert len(rows) == 1
    assert rows[0]["path"].endswith("a.wav")


def test_duplicates_and_versions(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)

    duplicates = data.duplicates(cfg)
    assert duplicates["total"] >= 1
    assert duplicates["by_kind"]
    assert duplicates["groups"][0]["members"]

    versions = data.versions(cfg)
    assert "counts" in versions and "samples" in versions


def test_integrations_reports_software(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)

    payload = data.integrations(cfg)

    assert payload["software"] == ["rekordbox", "serato"]
    by_name = {item["software"]: item for item in payload["reports"]}
    assert by_name["serato"]["available"] is False
    assert "configurado" in by_name["serato"]["error"]


def test_capabilities_lists_commands() -> None:
    payload = data.capabilities()

    names = {command["name"] for command in payload["commands"]}
    assert {"scan", "classify", "relink", "ui"} <= names
    assert payload["pipeline"][0]["layer"] == "L0"
    assert payload["safety"]


def test_overview_without_catalog_raises(tmp_path) -> None:
    config = tmp_path / "djlife.toml"
    missing = tmp_path / "nope.db"
    config.write_text(f'[catalog]\npath = "{missing.as_posix()}"\n', encoding="utf-8")

    with pytest.raises(data.CatalogUnavailable):
        data.overview(config_mod.load_config(config))


def test_resolve_asset_blocks_traversal() -> None:
    assert server.resolve_asset("index.html") is not None
    assert server.resolve_asset("../server.py") is None
    assert server.resolve_asset("nope.js") is None


def _serve(cfg):
    httpd = server.build_server(cfg, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, thread, f"http://{host}:{port}"


def test_server_serves_assets_and_api(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)
    httpd, thread, base = _serve(cfg)
    try:
        status, body = _get(f"{base}/")
        assert status == 200
        assert b"DJLIFE" in body

        status, body = _get(f"{base}/assets/app.css")
        assert status == 200
        assert b"--cyan" in body

        status, body = _get(f"{base}/assets/app.js")
        assert status == 200
        assert b"/api/overview" in body

        _, body = _get(f"{base}/api/overview")
        assert json.loads(body)["stats"]["files"] == 2

        _, body = _get(f"{base}/api/tracks?q=a.wav")
        assert len(json.loads(body)["tracks"]) == 1

        _, body = _get(f"{base}/api/duplicates")
        assert json.loads(body)["total"] >= 1

        _, body = _get(f"{base}/api/capabilities")
        assert any(cmd["name"] == "ui" for cmd in json.loads(body)["commands"])

        _, body = _get(f"{base}/api/version")
        assert json.loads(body)["name"] == "djlife"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_returns_404_for_unknown_routes(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)
    httpd, thread, base = _serve(cfg)
    try:
        for path in ("/api/nope", "/assets/nope.js", "/nao-existe"):
            with pytest.raises(urllib.error.HTTPError) as error:
                _get(f"{base}{path}")
            assert error.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_reports_missing_catalog(tmp_path, make_wav) -> None:
    cfg = _library(tmp_path, make_wav)
    cfg.db_path.unlink()
    httpd, thread, base = _serve(cfg)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _get(f"{base}/api/overview")
        assert error.value.code == 503
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
