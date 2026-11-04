import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from djlife import config as config_mod
from djlife import importer, premium
from djlife import license as license_mod
from djlife.config import Config, LicenseConfig
from djlife.ui import download, server

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


def _licensed_config(tmp_path: Path) -> tuple[Config, Path]:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key)
    license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-download",
        plan="lifetime",
        features=(premium.DOWNLOAD_FEATURE,),
        machine_hash_value=license_mod.machine_hash(),
        expires_at=None,
    )
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(
        f'[license]\npublic_key = "{public_key.as_posix()}"\n'
        f'license_file = "{license_file.as_posix()}"\n'
        f'admin_token = "{ADMIN_TOKEN}"\n',
        encoding="utf-8",
    )
    return config_mod.load_config(config_file), config_file


def _wait(job, timeout: float = 10.0):
    deadline = time.time() + timeout
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.05)
    return job


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


def test_clean_urls_normalizes() -> None:
    assert download.clean_urls("https://a\nhttps://b, https://a\n\nhttps://c") == [
        "https://a",
        "https://b",
        "https://c",
    ]
    assert download.clean_urls(["https://a", " https://b "]) == ["https://a", "https://b"]
    assert download.clean_urls(None) == []


def test_status_reports_gate_without_license() -> None:
    state = download.status(Config(license=LicenseConfig()))

    assert state["feature"] == premium.DOWNLOAD_FEATURE
    assert state["licensed"] is False
    assert state["reason"]
    assert state["ready"] is False


def test_start_probe_requires_urls(tmp_path) -> None:
    cfg, _ = _licensed_config(tmp_path)

    with pytest.raises(download.DownloadError):
        download.start_probe(cfg, [])


def test_start_probe_requires_license() -> None:
    with pytest.raises(download.DownloadUnavailable):
        download.start_probe(Config(), ["https://a"])


def test_start_probe_collects_candidates(tmp_path, monkeypatch) -> None:
    cfg, _ = _licensed_config(tmp_path)
    monkeypatch.setattr(importer, "available", lambda: True)
    monkeypatch.setattr(
        importer,
        "probe",
        lambda urls: [importer.ImportCandidate(urls[0], "Track", "Canal", 180.0, "webm")],
    )

    job = _wait(download.start_probe(cfg, ["https://a"]))

    assert job.status == "done"
    assert job.result["count"] == 1
    assert job.result["items"][0]["title"] == "Track"


def test_start_download_rejects_file_target(tmp_path, monkeypatch) -> None:
    cfg, _ = _licensed_config(tmp_path)
    monkeypatch.setattr(importer, "available", lambda: True)
    file_target = tmp_path / "not-a-dir"
    file_target.write_text("x", encoding="utf-8")

    with pytest.raises(download.DownloadError):
        download.start_download(cfg, ["https://a"], target=str(file_target))


def test_start_download_reports_outcomes(tmp_path, monkeypatch) -> None:
    cfg, _ = _licensed_config(tmp_path)
    monkeypatch.setattr(importer, "available", lambda: True)
    out = tmp_path / "downloads"

    def fake_download(urls, *, target_dir, audio_format):
        return [
            importer.DownloadOutcome(urls[0], Path(target_dir) / "Track [id].webm", True, "ok"),
            importer.DownloadOutcome("https://b", None, False, "erro"),
        ]

    monkeypatch.setattr(importer, "download", fake_download)

    job = _wait(download.start_download(cfg, ["https://a", "https://b"], target=str(out)))

    assert job.status == "done"
    assert job.result["total"] == 2
    assert job.result["ok"] == 1
    assert job.result["errors"] == 1
    assert "djlife scan" in job.result["scan_hint"]


def test_server_premium_status_and_probe(tmp_path, monkeypatch) -> None:
    cfg, config_file = _licensed_config(tmp_path)
    monkeypatch.setattr(importer, "available", lambda: True)
    monkeypatch.setattr(
        importer,
        "probe",
        lambda urls: [importer.ImportCandidate(urls[0], "Track", "Canal", 120.0, "webm")],
    )
    httpd, thread, base = _serve(cfg, config_file)
    try:
        _, body = _get(f"{base}/api/premium/status")
        state = json.loads(body)
        assert state["licensed"] is True
        assert state["ready"] is True

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/premium/probe", {"urls": ["https://a"]})
        assert error.value.code == 403

        _, body = _post(
            f"{base}/api/premium/probe",
            {"urls": ["https://a"]},
            {"X-Admin-Token": ADMIN_TOKEN},
        )
        assert json.loads(body)["task"] == "probe"

        payload = {"status": "running"}
        for _ in range(60):
            _, body = _get(f"{base}/api/premium/job?task=probe")
            payload = json.loads(body)
            if payload["status"] != "running":
                break
            time.sleep(0.05)
        assert payload["status"] == "done"
        assert payload["result"]["count"] == 1
    finally:
        _stop(httpd, thread)


def test_server_premium_requires_license(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(f'[license]\nadmin_token = "{ADMIN_TOKEN}"\n', encoding="utf-8")
    cfg = config_mod.load_config(config_file)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        _, body = _get(f"{base}/api/premium/status")
        assert json.loads(body)["licensed"] is False

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(
                f"{base}/api/premium/probe",
                {"urls": ["https://a"]},
                {"X-Admin-Token": ADMIN_TOKEN},
            )
        assert error.value.code == 403
    finally:
        _stop(httpd, thread)


def test_server_premium_requires_token(tmp_path, monkeypatch) -> None:
    cfg, config_file = _licensed_config(tmp_path)
    monkeypatch.setattr(importer, "available", lambda: True)
    httpd, thread, base = _serve(cfg, config_file)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/premium/download", {"urls": ["https://a"]})
        assert error.value.code == 403

        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/premium/probe", {"urls": []}, {"X-Admin-Token": ADMIN_TOKEN})
        assert error.value.code == 400
    finally:
        _stop(httpd, thread)
