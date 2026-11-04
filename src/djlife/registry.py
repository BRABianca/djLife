"""Registro local das licencas emitidas (fonte do painel de administracao).

Guarda em um unico JSON o historico das licencas emitidas pelo vendor: cliente,
plano, maquina, datas e status (active/revoked). E independente do catalogo
musical e nunca escreve no filesystem do cliente.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from djlife import license as license_mod

APP_NAME = "djlife"
REGISTRY_SCHEMA = 1
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"


class RegistryError(RuntimeError):
    """Falha ao ler ou gravar o registro de licencas."""


@dataclass(frozen=True)
class LicenseRecord:
    id: str
    customer_id: str
    plan: str
    machine_hash: str | None
    features: tuple[str, ...]
    issued_at: str
    expires_at: str | None
    key_id: str
    license_path: str
    status: str = STATUS_ACTIVE
    revoked_at: str | None = None
    note: str | None = None


def default_registry_path() -> Path:
    return Path(user_data_dir(APP_NAME)) / "licenses_registry.json"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def record_from_envelope(
    envelope: license_mod.LicenseEnvelope,
    *,
    license_path: Path | str,
    record_id: str | None = None,
) -> LicenseRecord:
    """Converte uma licenca recem-emitida em registro do painel."""
    claims = envelope.claims
    return LicenseRecord(
        id=record_id or new_id(),
        customer_id=claims.customer_id,
        plan=claims.plan,
        machine_hash=claims.machine_hash,
        features=tuple(claims.features),
        issued_at=claims.issued_at,
        expires_at=claims.expires_at,
        key_id=envelope.key_id,
        license_path=str(license_path),
    )


def effective_status(record: LicenseRecord, *, now: datetime | None = None) -> str:
    """Status derivado: revogada tem precedencia, depois expiracao."""
    if record.status == STATUS_REVOKED:
        return STATUS_REVOKED
    expires_at = _parse_dt(record.expires_at)
    if expires_at is not None and (now or license_mod.utcnow()) > expires_at:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


def to_payload(record: LicenseRecord, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "id": record.id,
        "customer_id": record.customer_id,
        "plan": record.plan,
        "machine_hash": record.machine_hash,
        "features": list(record.features),
        "issued_at": record.issued_at,
        "expires_at": record.expires_at,
        "key_id": record.key_id,
        "license_path": record.license_path,
        "status": record.status,
        "revoked_at": record.revoked_at,
        "note": record.note,
        "effective_status": effective_status(record, now=now),
    }


def _record_from_payload(payload: dict[str, Any]) -> LicenseRecord:
    return LicenseRecord(
        id=str(payload["id"]),
        customer_id=str(payload["customer_id"]),
        plan=str(payload["plan"]),
        machine_hash=str(payload["machine_hash"]) if payload.get("machine_hash") else None,
        features=tuple(str(value) for value in payload.get("features", ())),
        issued_at=str(payload["issued_at"]),
        expires_at=str(payload["expires_at"]) if payload.get("expires_at") else None,
        key_id=str(payload.get("key_id", "")),
        license_path=str(payload.get("license_path", "")),
        status=str(payload.get("status", STATUS_ACTIVE)),
        revoked_at=str(payload["revoked_at"]) if payload.get("revoked_at") else None,
        note=str(payload["note"]) if payload.get("note") else None,
    )


def load_records(path: Path | str | None = None) -> list[LicenseRecord]:
    """Le o registro; arquivo ausente devolve lista vazia."""
    target = Path(path) if path else default_registry_path()
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"registro de licencas ilegivel: {target} ({exc})") from exc
    return [_record_from_payload(item) for item in payload.get("licenses", ())]


def save_records(records: list[LicenseRecord], path: Path | str | None = None) -> Path:
    target = Path(path) if path else default_registry_path()
    payload = {
        "version": REGISTRY_SCHEMA,
        "licenses": [to_payload(record) for record in records],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def find_record(records: list[LicenseRecord], record_id: str) -> LicenseRecord | None:
    return next((record for record in records if record.id == record_id), None)


def add_record(record: LicenseRecord, path: Path | str | None = None) -> Path:
    records = load_records(path)
    records.append(record)
    return save_records(records, path)


def revoke_record(
    record_id: str,
    *,
    path: Path | str | None = None,
    reason: str | None = None,
) -> LicenseRecord:
    records = load_records(path)
    record = find_record(records, record_id)
    if record is None:
        raise RegistryError(f"licenca nao encontrada no registro: {record_id}")
    updated = replace(
        record,
        status=STATUS_REVOKED,
        revoked_at=_isoformat(license_mod.utcnow()),
        note=reason or record.note,
    )
    save_records([updated if item.id == record_id else item for item in records], path)
    return updated


def renew_record(
    record_id: str,
    envelope: license_mod.LicenseEnvelope,
    *,
    path: Path | str | None = None,
    license_path: Path | str | None = None,
) -> LicenseRecord:
    records = load_records(path)
    record = find_record(records, record_id)
    if record is None:
        raise RegistryError(f"licenca nao encontrada no registro: {record_id}")
    if record.status == STATUS_REVOKED:
        raise RegistryError("licenca revogada: emita uma nova em vez de renovar")
    claims = envelope.claims
    updated = replace(
        record,
        plan=claims.plan,
        features=tuple(claims.features),
        expires_at=claims.expires_at,
        issued_at=claims.issued_at,
        key_id=envelope.key_id,
        license_path=str(license_path) if license_path else record.license_path,
    )
    save_records([updated if item.id == record_id else item for item in records], path)
    return updated
