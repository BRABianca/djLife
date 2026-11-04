from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from platformdirs import user_data_dir

APP_NAME = "djlife"
LICENSE_SCHEMA = 1


class LicenseError(RuntimeError):
    """Falha de licenciamento offline."""


@dataclass(frozen=True)
class LicenseClaims:
    schema: int
    customer_id: str
    plan: str
    issued_at: str
    expires_at: str | None
    machine_hash: str | None
    features: tuple[str, ...]
    issuer: str | None = None


@dataclass(frozen=True)
class LicenseEnvelope:
    key_id: str
    claims: LicenseClaims
    signature: str


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    reason: str
    customer_id: str | None = None
    plan: str | None = None
    expires_at: str | None = None
    machine_hash: str | None = None
    machine_match: bool | None = None
    features: tuple[str, ...] = ()
    key_id: str | None = None


def default_license_path() -> Path:
    return Path(user_data_dir(APP_NAME)) / "license.json"


def default_public_key_path() -> Path:
    return Path(user_data_dir(APP_NAME)) / "license_public_key.pem"


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _canonical_claims(claims: LicenseClaims) -> bytes:
    payload = {
        "customer_id": claims.customer_id,
        "expires_at": claims.expires_at,
        "features": list(claims.features),
        "issued_at": claims.issued_at,
        "issuer": claims.issuer,
        "machine_hash": claims.machine_hash,
        "plan": claims.plan,
        "schema": claims.schema,
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def _read_windows_machine_guid() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        ) as handle:
            value, _ = winreg.QueryValueEx(handle, "MachineGuid")
            return str(value)
    except OSError:
        return None


def _read_linux_machine_id() -> str | None:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _read_macos_uuid() -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        output = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    marker = "IOPlatformUUID"
    for line in output.splitlines():
        if marker in line:
            return line.split("=", 1)[1].strip().strip('"')
    return None


def machine_hash() -> str:
    raw = (
        _read_windows_machine_guid()
        or _read_linux_machine_id()
        or _read_macos_uuid()
        or f"{uuid.getnode():012x}:{platform.node()}:{platform.machine()}"
    )
    payload = f"{platform.system()}|{platform.machine()}|{raw}".encode()
    return hashlib.sha256(payload).hexdigest()


def machine_summary() -> dict[str, str]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "node": platform.node(),
        "hash": machine_hash(),
    }


def load_private_key(path: Path | str) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseError("Chave privada invalida para Ed25519.")
    return key


def load_public_key(path: Path | str) -> Ed25519PublicKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseError("Chave publica invalida para Ed25519.")
    return key


def generate_keypair(private_path: Path | str, public_path: Path | str) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_out = Path(private_path)
    public_out = Path(public_path)
    private_out.parent.mkdir(parents=True, exist_ok=True)
    public_out.parent.mkdir(parents=True, exist_ok=True)
    private_out.write_bytes(private_bytes)
    public_out.write_bytes(public_bytes)
    return private_out, public_out


def issue_license(
    private_key_path: Path | str,
    output_path: Path | str,
    *,
    customer_id: str,
    plan: str,
    features: tuple[str, ...],
    machine_hash_value: str | None,
    expires_at: datetime | None,
    issuer: str | None = None,
) -> LicenseEnvelope:
    private_key = load_private_key(private_key_path)
    public_key = private_key.public_key()
    claims = LicenseClaims(
        schema=LICENSE_SCHEMA,
        customer_id=customer_id,
        plan=plan,
        issued_at=_isoformat(utcnow()),
        expires_at=_isoformat(expires_at) if expires_at else None,
        machine_hash=machine_hash_value,
        features=tuple(sorted(set(features))),
        issuer=issuer,
    )
    signature = private_key.sign(_canonical_claims(claims))
    envelope = LicenseEnvelope(
        key_id=_key_id(public_key),
        claims=claims,
        signature=_b64encode(signature),
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "key_id": envelope.key_id,
        "claims": asdict(claims),
        "signature": envelope.signature,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return envelope


def load_license(path: Path | str) -> LicenseEnvelope:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    claims_data = payload["claims"]
    claims = LicenseClaims(
        schema=int(claims_data["schema"]),
        customer_id=str(claims_data["customer_id"]),
        plan=str(claims_data["plan"]),
        issued_at=str(claims_data["issued_at"]),
        expires_at=str(claims_data["expires_at"]) if claims_data.get("expires_at") else None,
        machine_hash=(
            str(claims_data["machine_hash"]) if claims_data.get("machine_hash") else None
        ),
        features=tuple(str(value) for value in claims_data.get("features", ())),
        issuer=str(claims_data["issuer"]) if claims_data.get("issuer") else None,
    )
    return LicenseEnvelope(
        key_id=str(payload["key_id"]),
        claims=claims,
        signature=str(payload["signature"]),
    )


def verify_envelope(
    envelope: LicenseEnvelope,
    public_key: Ed25519PublicKey,
    *,
    now: datetime | None = None,
    current_machine_hash: str | None = None,
    required_features: tuple[str, ...] = (),
) -> LicenseStatus:
    if envelope.claims.schema != LICENSE_SCHEMA:
        return LicenseStatus(False, "schema-incompativel", key_id=envelope.key_id)

    if envelope.key_id != _key_id(public_key):
        return LicenseStatus(False, "chave-publica-diferente", key_id=envelope.key_id)

    try:
        public_key.verify(_b64decode(envelope.signature), _canonical_claims(envelope.claims))
    except InvalidSignature:
        return LicenseStatus(False, "assinatura-invalida", key_id=envelope.key_id)

    current = now or utcnow()
    expires_at = _parse_dt(envelope.claims.expires_at)
    if expires_at is not None and current > expires_at:
        return LicenseStatus(
            False,
            "licenca-expirada",
            customer_id=envelope.claims.customer_id,
            plan=envelope.claims.plan,
            expires_at=envelope.claims.expires_at,
            machine_hash=envelope.claims.machine_hash,
            machine_match=(
                envelope.claims.machine_hash == current_machine_hash
                if envelope.claims.machine_hash and current_machine_hash
                else None
            ),
            features=envelope.claims.features,
            key_id=envelope.key_id,
        )

    machine_match: bool | None = None
    if envelope.claims.machine_hash:
        machine_match = envelope.claims.machine_hash == current_machine_hash
        if machine_match is False:
            return LicenseStatus(
                False,
                "maquina-diferente",
                customer_id=envelope.claims.customer_id,
                plan=envelope.claims.plan,
                expires_at=envelope.claims.expires_at,
                machine_hash=envelope.claims.machine_hash,
                machine_match=False,
                features=envelope.claims.features,
                key_id=envelope.key_id,
            )

    missing = tuple(
        feature for feature in required_features if feature not in envelope.claims.features
    )
    if missing:
        return LicenseStatus(
            False,
            f"recurso-ausente:{','.join(missing)}",
            customer_id=envelope.claims.customer_id,
            plan=envelope.claims.plan,
            expires_at=envelope.claims.expires_at,
            machine_hash=envelope.claims.machine_hash,
            machine_match=machine_match,
            features=envelope.claims.features,
            key_id=envelope.key_id,
        )

    return LicenseStatus(
        True,
        "ok",
        customer_id=envelope.claims.customer_id,
        plan=envelope.claims.plan,
        expires_at=envelope.claims.expires_at,
        machine_hash=envelope.claims.machine_hash,
        machine_match=machine_match,
        features=envelope.claims.features,
        key_id=envelope.key_id,
    )


def verify_license_file(
    license_path: Path | str,
    public_key_path: Path | str,
    *,
    required_features: tuple[str, ...] = (),
) -> LicenseStatus:
    envelope = load_license(license_path)
    public_key = load_public_key(public_key_path)
    return verify_envelope(
        envelope,
        public_key,
        current_machine_hash=machine_hash(),
        required_features=required_features,
    )


def status_from_paths(
    *,
    license_path: Path | str | None,
    public_key_path: Path | str | None,
    required_features: tuple[str, ...] = (),
) -> LicenseStatus:
    if public_key_path is None or not Path(public_key_path).exists():
        return LicenseStatus(False, "chave-publica-ausente")
    if license_path is None or not Path(license_path).exists():
        return LicenseStatus(False, "licenca-ausente")
    try:
        return verify_license_file(
            Path(license_path), Path(public_key_path), required_features=required_features
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, LicenseError) as exc:
        return LicenseStatus(False, f"licenca-invalida:{exc}")


def status_payload(status: LicenseStatus) -> dict[str, Any]:
    return {
        "valid": status.valid,
        "reason": status.reason,
        "customer_id": status.customer_id,
        "plan": status.plan,
        "expires_at": status.expires_at,
        "machine_hash": status.machine_hash,
        "machine_match": status.machine_match,
        "features": list(status.features),
        "key_id": status.key_id,
    }
