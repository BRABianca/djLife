from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from djlife import admin, premium, registry
from djlife import license as license_mod
from djlife.config import Config, LicenseConfig
from djlife.ui import server


def _cfg(tmp_path: Path, *, token: str | None = "segredo") -> Config:
    return Config(
        license=LicenseConfig(
            public_key=tmp_path / "public.pem",
            license_file=tmp_path / "license.json",
            private_key=tmp_path / "private.pem",
            registry_file=tmp_path / "registry.json",
            admin_token=token,
        )
    )


def _keypair(cfg: Config, *, passphrase: str | None = None) -> None:
    license_mod.generate_keypair(
        cfg.license.private_key_path,
        cfg.license.public_key_path,
        passphrase=passphrase,
    )


def test_require_token_blocks_when_disabled(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, token=None)

    assert admin.is_enabled(cfg) is False
    with pytest.raises(admin.AdminUnavailable):
        admin.require_token(cfg, "qualquer")


def test_require_token_rejects_wrong_token(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    with pytest.raises(admin.AdminUnavailable):
        admin.require_token(cfg, "errado")
    with pytest.raises(admin.AdminUnavailable):
        admin.require_token(cfg, None)
    admin.require_token(cfg, "segredo")


def test_issue_registers_and_verifies(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)

    result = admin.issue(
        cfg,
        customer_id="cliente-1",
        plan="lifetime",
        bind_current_machine=True,
        days=30,
    )

    assert set(result["claims"]["features"]) == set(premium.feature_codes())
    assert result["record"]["effective_status"] == "active"
    assert Path(result["path"]).exists()

    records = registry.load_records(cfg.license.registry_path)
    assert len(records) == 1

    status = license_mod.verify_license_file(
        result["path"],
        cfg.license.public_key_path,
        required_features=(premium.DOWNLOAD_FEATURE,),
    )
    assert status.valid is True
    assert status.machine_match is True


def test_owner_license_grants_every_feature(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)

    result = admin.issue(
        cfg,
        customer_id="dona",
        plan=premium.OWNER_PLAN,
        bind_current_machine=True,
    )

    assert result["claims"]["features"] == (premium.WILDCARD_FEATURE,)
    status = license_mod.verify_license_file(
        result["path"],
        cfg.license.public_key_path,
        required_features=("premium.recurso.futuro",),
    )
    assert status.valid is True


def test_issue_with_encrypted_private_key(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg, passphrase="segredo")

    with pytest.raises(license_mod.LicenseError):
        admin.issue(cfg, customer_id="c", plan="lifetime", passphrase=None)

    result = admin.issue(cfg, customer_id="c", plan="lifetime", passphrase="segredo")
    assert result["key_id"]


def test_renew_and_revoke(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)
    issued = admin.issue(
        cfg,
        customer_id="c",
        plan="monthly",
        bind_current_machine=True,
        days=10,
    )
    record_id = issued["record"]["id"]

    renewed = admin.renew(cfg, record_id, days=90)
    assert renewed["record"]["expires_at"] is not None

    revoked = admin.revoke(cfg, record_id, reason="chargeback")
    assert revoked["record"]["effective_status"] == "revoked"

    with pytest.raises(registry.RegistryError):
        admin.renew(cfg, record_id, days=10)


def test_renew_unknown_record_raises(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    with pytest.raises(registry.RegistryError):
        admin.renew(cfg, "nao-existe", days=10)


def test_registry_effective_status_expires(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)
    admin.issue(cfg, customer_id="c", plan="monthly", expires="2020-01-01")

    record = registry.load_records(cfg.license.registry_path)[0]

    assert registry.effective_status(record) == registry.STATUS_EXPIRED


def test_activate_owner_installs_wildcard_license(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    result = admin.activate_owner(cfg, customer_id="dona", encrypt=False)

    assert cfg.license.license_path.exists()
    assert cfg.license.public_key_path.exists()
    assert premium.is_owner(cfg) is True
    assert license_mod.load_license(cfg.license.license_path).claims.features == (
        premium.WILDCARD_FEATURE,
    )
    assert result["record"]["plan"] == premium.OWNER_PLAN


def _serve(cfg: Config) -> tuple[server.ThreadingHTTPServer, threading.Thread, str]:
    httpd = server.build_server(cfg, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, thread, f"http://{host}:{port}"


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, object]]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_admin_endpoints_require_token(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)
    httpd, thread, base = _serve(cfg)
    try:
        status, payload = _request(f"{base}/api/admin/status")
        assert status == 200
        assert payload["enabled"] is True
        assert payload["owner"] is False

        with pytest.raises(urllib.error.HTTPError) as error:
            _request(f"{base}/api/admin/licenses")
        assert error.value.code == 403

        status, payload = _request(
            f"{base}/api/admin/issue",
            method="POST",
            body={
                "customer_id": "cliente-9",
                "plan": "lifetime",
                "bind_current_machine": True,
            },
            token="segredo",
        )
        assert status == 200
        record = payload["record"]
        assert record["customer_id"] == "cliente-9"

        _, listing = _request(f"{base}/api/admin/licenses", token="segredo")
        assert len(listing["licenses"]) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_admin_issue_rejects_missing_token(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _keypair(cfg)
    httpd, thread, base = _serve(cfg)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _request(
                f"{base}/api/admin/issue",
                method="POST",
                body={"customer_id": "x", "plan": "lifetime"},
                token="errado",
            )
        assert error.value.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_admin_status_disabled_without_token(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, token=None)
    httpd, thread, base = _serve(cfg)
    try:
        status, payload = _request(f"{base}/api/admin/status")
        assert status == 200
        assert payload["enabled"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
