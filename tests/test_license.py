from __future__ import annotations

from datetime import timedelta

import pytest

from djlife import license as license_mod


def test_generate_issue_and_verify_license(tmp_path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key)

    machine = license_mod.machine_hash()
    license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-1",
        plan="lifetime",
        features=("premium.ytdlp_import",),
        machine_hash_value=machine,
        expires_at=None,
        issuer="bianca",
    )

    status = license_mod.verify_license_file(license_file, public_key)

    assert status.valid is True
    assert status.customer_id == "cliente-1"
    assert status.plan == "lifetime"
    assert status.machine_match is True


def test_license_rejects_wrong_machine(tmp_path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key)

    license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-2",
        plan="monthly",
        features=("premium.ytdlp_import",),
        machine_hash_value="outra-maquina",
        expires_at=None,
    )

    status = license_mod.verify_license_file(license_file, public_key)

    assert status.valid is False
    assert status.reason == "maquina-diferente"


def test_license_rejects_expired_license(tmp_path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key)

    envelope = license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-3",
        plan="monthly",
        features=("premium.ytdlp_import",),
        machine_hash_value=license_mod.machine_hash(),
        expires_at=license_mod.utcnow() - timedelta(days=1),
    )
    status = license_mod.verify_envelope(
        envelope,
        license_mod.load_public_key(public_key),
        now=license_mod.utcnow(),
        current_machine_hash=license_mod.machine_hash(),
    )

    assert status.valid is False
    assert status.reason == "licenca-expirada"


def test_status_from_paths_reports_missing_files(tmp_path) -> None:
    status = license_mod.status_from_paths(
        license_path=tmp_path / "license.json",
        public_key_path=tmp_path / "public.pem",
    )

    assert status.valid is False
    assert status.reason == "chave-publica-ausente"


def test_feature_granted_with_wildcard() -> None:
    assert license_mod.feature_granted((license_mod.WILDCARD_FEATURE,), "premium.novo") is True
    assert license_mod.feature_granted(("premium.ytdlp_import",), "premium.ytdlp_import") is True
    assert license_mod.feature_granted(("premium.ytdlp_import",), "premium.crates") is False


def test_encrypted_private_key_requires_passphrase(tmp_path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key, passphrase="segredo")

    with pytest.raises(license_mod.LicenseError):
        license_mod.issue_license(
            private_key,
            license_file,
            customer_id="cliente-4",
            plan="lifetime",
            features=("premium.ytdlp_import",),
            machine_hash_value=None,
            expires_at=None,
        )

    envelope = license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-4",
        plan="lifetime",
        features=("premium.ytdlp_import",),
        machine_hash_value=None,
        expires_at=None,
        private_key_password="segredo",
    )
    assert envelope.key_id


def test_parse_expiration_handles_days_and_dates() -> None:
    assert license_mod.parse_expiration() is None

    target = license_mod.parse_expiration(expires="2030-01-01")
    assert target is not None and target.year == 2030

    days = license_mod.parse_expiration(days=30)
    assert days is not None and days > license_mod.utcnow()

    with pytest.raises(ValueError):
        license_mod.parse_expiration(days=1, expires="2030-01-01")
