"""Operacoes de administracao (painel da dona) para gestao de licencas.

Centraliza emitir/renovar/revogar e a ativacao do modo owner. Escreve apenas o
registro local JSON (`registry.py`) e arquivos de licenca; nunca toca no catalogo
musical nem na biblioteca. O acesso e protegido pelo token `admin_token` do
`djlife.toml` (comparacao em tempo constante).
"""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from djlife import license as license_mod
from djlife import premium, registry
from djlife.config import Config

ADMIN_NOTE = (
    "Revogacao e local: nao desliga uma licenca ja entregue e verificada offline (nao e DRM)."
)


class AdminUnavailable(RuntimeError):
    """Painel de administracao desabilitado ou credencial invalida."""


def is_enabled(cfg: Config) -> bool:
    return bool(cfg.license.admin_token)


def require_token(cfg: Config, token: str | None) -> None:
    expected = cfg.license.admin_token
    if not expected:
        raise AdminUnavailable(
            "Painel admin desabilitado: defina [license] admin_token no djlife.toml."
        )
    if not token or not hmac.compare_digest(token, expected):
        raise AdminUnavailable("Token de administracao invalido.")


def status_public(cfg: Config) -> dict[str, Any]:
    """Resumo sem dados sensiveis para a UI decidir exibir a aba."""
    return {"enabled": is_enabled(cfg), "owner": premium.is_owner(cfg)}


def status_detail(cfg: Config) -> dict[str, Any]:
    license_cfg = cfg.license
    return {
        "enabled": is_enabled(cfg),
        "owner": premium.is_owner(cfg),
        "registry_path": str(license_cfg.registry_path),
        "private_key": str(license_cfg.private_key_path),
        "public_key": str(license_cfg.public_key_path),
        "has_private_key": license_cfg.private_key_path.exists(),
        "has_public_key": license_cfg.public_key_path.exists(),
        "note": ADMIN_NOTE,
    }


def resolve_features(plan: str, features: Sequence[str] | None) -> tuple[str, ...]:
    if features:
        return tuple(features)
    if plan == premium.OWNER_PLAN:
        return premium.owner_features()
    return premium.feature_codes()


def default_license_output(cfg: Config, customer_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in customer_id)
    return cfg.license.registry_path.parent / "issued" / f"license-{safe or 'cliente'}.json"


def licenses_payload(cfg: Config) -> dict[str, Any]:
    records = registry.load_records(cfg.license.registry_path)
    return {
        "registry_path": str(cfg.license.registry_path),
        "total": len(records),
        "licenses": [registry.to_payload(record) for record in records],
        "note": ADMIN_NOTE,
    }


def issue(
    cfg: Config,
    *,
    customer_id: str,
    plan: str,
    features: Sequence[str] | None = None,
    machine_hash: str | None = None,
    bind_current_machine: bool = False,
    days: int | None = None,
    expires: str | None = None,
    issuer: str | None = None,
    output: Path | str | None = None,
    passphrase: str | None = None,
    private_key: Path | str | None = None,
) -> dict[str, Any]:
    """Emite uma licenca assinada e a registra no painel."""
    bound = license_mod.machine_hash() if bind_current_machine else machine_hash
    resolved = resolve_features(plan, features)
    out = Path(output) if output else default_license_output(cfg, customer_id)
    key_path = Path(private_key) if private_key else cfg.license.private_key_path
    envelope = license_mod.issue_license(
        key_path,
        out,
        customer_id=customer_id,
        plan=plan,
        features=resolved,
        machine_hash_value=bound,
        expires_at=license_mod.parse_expiration(days, expires),
        issuer=issuer,
        private_key_password=passphrase,
    )
    record = registry.record_from_envelope(envelope, license_path=out)
    registry.add_record(record, cfg.license.registry_path)
    return {
        "path": str(out),
        "key_id": envelope.key_id,
        "claims": asdict(envelope.claims),
        "record": registry.to_payload(record),
    }


def renew(
    cfg: Config,
    record_id: str,
    *,
    plan: str | None = None,
    features: Sequence[str] | None = None,
    days: int | None = None,
    expires: str | None = None,
    issuer: str | None = None,
    passphrase: str | None = None,
    private_key: Path | str | None = None,
) -> dict[str, Any]:
    """Reemite a licenca de um registro ativo, atualizando validade/plano."""
    records = registry.load_records(cfg.license.registry_path)
    record = registry.find_record(records, record_id)
    if record is None:
        raise registry.RegistryError(f"licenca nao encontrada no registro: {record_id}")
    target_plan = plan or record.plan
    resolved = resolve_features(target_plan, features or record.features)
    out = (
        Path(record.license_path)
        if record.license_path
        else default_license_output(cfg, record.customer_id)
    )
    key_path = Path(private_key) if private_key else cfg.license.private_key_path
    envelope = license_mod.issue_license(
        key_path,
        out,
        customer_id=record.customer_id,
        plan=target_plan,
        features=resolved,
        machine_hash_value=record.machine_hash,
        expires_at=license_mod.parse_expiration(days, expires),
        issuer=issuer,
        private_key_password=passphrase,
    )
    updated = registry.renew_record(
        record_id,
        envelope,
        path=cfg.license.registry_path,
        license_path=out,
    )
    return {
        "path": str(out),
        "key_id": envelope.key_id,
        "record": registry.to_payload(updated),
    }


def revoke(cfg: Config, record_id: str, *, reason: str | None = None) -> dict[str, Any]:
    """Marca um registro como revogado no painel (nao desliga licenca entregue)."""
    updated = registry.revoke_record(record_id, path=cfg.license.registry_path, reason=reason)
    return {"record": registry.to_payload(updated), "note": ADMIN_NOTE}


def activate_owner(
    cfg: Config,
    *,
    customer_id: str,
    passphrase: str | None = None,
    encrypt: bool = True,
    issuer: str | None = None,
) -> dict[str, Any]:
    """Gera o par de chaves, emite a licenca owner (curinga) e a instala localmente."""
    secret = passphrase if encrypt else None
    private_path, public_path = license_mod.generate_keypair(
        cfg.license.private_key_path,
        cfg.license.public_key_path,
        passphrase=secret,
    )
    envelope = license_mod.issue_license(
        private_path,
        cfg.license.license_path,
        customer_id=customer_id,
        plan=premium.OWNER_PLAN,
        features=premium.owner_features(),
        machine_hash_value=license_mod.machine_hash(),
        expires_at=None,
        issuer=issuer,
        private_key_password=secret,
    )
    record = registry.record_from_envelope(envelope, license_path=cfg.license.license_path)
    registry.add_record(record, cfg.license.registry_path)
    return {
        "private_key": str(private_path),
        "public_key": str(public_path),
        "license": str(cfg.license.license_path),
        "key_id": envelope.key_id,
        "record": registry.to_payload(record),
    }
