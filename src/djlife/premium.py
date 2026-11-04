"""Catalogo local de ofertas premium do djLife.

Nesta fase o modulo descreve planos, recursos e dependencias opcionais que
compoem a camada premium do produto. A venda/liberacao e interpessoal e manual,
sem gateway ou intermediario embutido no app.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from djlife import importer
from djlife import license as license_mod
from djlife.config import Config


@dataclass(frozen=True)
class PremiumPlan:
    code: str
    name: str
    billing: str
    cta: str
    detail: str


@dataclass(frozen=True)
class PremiumFeature:
    code: str
    name: str
    included_in: tuple[str, ...]
    status: str
    detail: str


DOWNLOAD_FEATURE = "premium.download"
ASSISTED_CURATION_FEATURE = "premium.assisted_curation"
OWNER_PLAN = license_mod.OWNER_PLAN
WILDCARD_FEATURE = license_mod.WILDCARD_FEATURE


PLANS: tuple[PremiumPlan, ...] = (
    PremiumPlan(
        code="monthly",
        name="Premium mensal",
        billing="acordo mensal",
        cta="Liberar plano mensal",
        detail=(
            "Acesso recorrente aos recursos premium com combinacao direta entre voce e o cliente."
        ),
    ),
    PremiumPlan(
        code="lifetime",
        name="Premium vitalicio",
        billing="pagamento unico",
        cta="Liberar acesso vitalicio",
        detail="Liberacao permanente dos recursos premium por venda direta, sem mensalidade.",
    ),
)


FEATURES: tuple[PremiumFeature, ...] = (
    PremiumFeature(
        code=DOWNLOAD_FEATURE,
        name="Download online",
        included_in=("monthly", "lifetime"),
        status="ativo",
        detail=(
            "Baixa audio e metadados de fontes suportadas (comando `djlife import`"
            " e painel de download na aba premium)."
        ),
    ),
    PremiumFeature(
        code=ASSISTED_CURATION_FEATURE,
        name="Curadoria assistida",
        included_in=("monthly", "lifetime"),
        status="ativo",
        detail=(
            "Fila de conflitos de genero revisavel na aba premium: escolha o genero correto"
            " e grave a decisao manual (source=manual), realimentando a camada `learned`."
        ),
    ),
    PremiumFeature(
        code="premium.crates",
        name="Ferramentas avancadas de crate",
        included_in=("monthly", "lifetime"),
        status="planejado",
        detail="Recortes premium para montar crates, selecoes e exports orientados por contexto.",
    ),
)


class PremiumUnavailable(RuntimeError):
    """O recurso premium nao esta liberado para esta instalacao."""


def feature_codes() -> tuple[str, ...]:
    return tuple(feature.code for feature in FEATURES)


def owner_features() -> tuple[str, ...]:
    """Recursos da licenca owner: curinga que libera todos os recursos premium."""
    return (WILDCARD_FEATURE,)


def is_owner(cfg: Config) -> bool:
    """Verdadeiro quando a licenca carregada e do plano owner (acesso total)."""
    status = license_status(cfg)
    return status.valid and status.plan == OWNER_PLAN


def license_status(cfg: Config) -> license_mod.LicenseStatus:
    return license_mod.status_from_paths(
        license_path=cfg.license.license_path,
        public_key_path=cfg.license.public_key_path,
    )


def require_feature(cfg: Config, feature_code: str) -> None:
    status = license_mod.status_from_paths(
        license_path=cfg.license.license_path,
        public_key_path=cfg.license.public_key_path,
        required_features=(feature_code,),
    )
    if not status.valid:
        raise PremiumUnavailable(
            "Recurso premium indisponivel: "
            f"{feature_code} ({status.reason}). Use `djlife license status`."
        )


def as_payload(cfg: Config | None = None) -> dict[str, object]:
    """Serializa os metadados premium para a UI/API."""
    current = (
        license_status(cfg)
        if cfg is not None
        else license_mod.LicenseStatus(False, "status-nao-carregado", features=feature_codes())
    )
    status = license_mod.status_payload(current)
    return {
        "enabled": True,
        "owner": current.valid and current.plan == OWNER_PLAN,
        "checkout": "manual/interpessoal",
        "plans": [asdict(plan) for plan in PLANS],
        "features": [asdict(feature) for feature in FEATURES],
        "notice": (
            "Camada premium preparada no app. A liberacao mensal/vitalicia pode ser feita"
            " manualmente, de forma interpessoal, sem intermediario dentro do produto."
        ),
        "install": 'pip install -e ".[premium]"',
        "download": {
            "feature": DOWNLOAD_FEATURE,
            "backend_available": importer.available(),
            "install": importer.INSTALL_HINT,
        },
        "license": status,
    }
