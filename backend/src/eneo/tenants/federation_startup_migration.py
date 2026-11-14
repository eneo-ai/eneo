from __future__ import annotations

from typing import Any

from dependency_injector import providers
from pydantic import ValidationError

from eneo.database.database import sessionmanager
from eneo.main.config import (
    Settings,
    canonicalize_legacy_redirect_path,
    get_settings,
    has_env_oidc_client,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant_federation_service import (
    SetFederationRequest,
    TenantFederationService,
)
from eneo.tenants.tenant_repo import TenantRepository

logger = get_logger(__name__)

_FULL_CONFIG_FIELDS = {
    "provider",
    "issuer",
    "discovery_endpoint",
    "authorization_endpoint",
    "token_endpoint",
    "userinfo_endpoint",
    "jwks_uri",
    "client_id",
    "client_secret",
    "scopes",
    "allowed_domains",
    "token_endpoint_auth_method",
    "token_endpoint_auth_methods_supported",
    "claims_mapping",
    "encrypted_at",
}
_REDIRECT_ONLY_FIELDS = {
    "canonical_public_origin",
    "redirect_path",
    "additional_redirect_uris",
}


class FederationStartupMigrationService:
    def __init__(
        self,
        tenant_repo: TenantRepository,
        encryption_service: EncryptionService,
        federation_service: TenantFederationService,
        settings: Settings,
    ) -> None:
        super().__init__()
        self.tenant_repo = tenant_repo
        self.encryption_service = encryption_service
        self.federation_service = federation_service
        self.settings = settings

    async def migrate_env_oidc_to_tenant_federation(self) -> bool:
        if not self.settings.federation_enabled:
            logger.debug(
                "Skipping federation startup migration because federation is disabled"
            )
            return False

        if not has_env_oidc_client(self.settings):
            logger.info(
                "Skipping federation startup migration because OIDC env configuration is incomplete"
            )
            return False

        if not self.encryption_service.is_active():
            raise ValueError(
                "Federation startup migration requires ENCRYPTION_KEY to encrypt client_secret"
            )

        active_tenants = await self.tenant_repo.get_all_active()
        if len(active_tenants) == 0 or len(active_tenants) > 1:
            logger.info(
                "Skipping federation startup migration because active tenant count is not exactly one",
                extra={"active_tenant_count": len(active_tenants)},
            )
            return False

        tenant = active_tenants[0]
        if not self._is_migration_eligible(tenant.federation_config):
            logger.info(
                "Skipping federation startup migration because tenant already has non-migratable federation config",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "existing_keys": sorted(tenant.federation_config.keys()),
                },
            )
            return False

        # The federation owner validates, encrypts, locks and audits the write.
        await self.federation_service.store_env_settings(
            tenant,
            self._registration(tenant.federation_config),
            expected=tenant.federation_config,
        )

        logger.info(
            "Migrated env OIDC configuration into tenant federation config",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "preserved_redirect_fields": sorted(
                    set(tenant.federation_config.keys()) & _REDIRECT_ONLY_FIELDS
                ),
            },
        )
        return True

    def _registration(self, existing_config: dict[str, Any]) -> SetFederationRequest:
        """The OIDC_* settings as the operator would register them, keeping the
        tenant's redirect settings and the domains that decide who signs in."""
        redirect = {
            field: existing_config[field]
            for field in _REDIRECT_ONLY_FIELDS
            if field in existing_config
        }
        if isinstance(redirect.get("redirect_path"), str):
            redirect["redirect_path"] = canonicalize_legacy_redirect_path(
                redirect["redirect_path"]
            )
        try:
            return SetFederationRequest(
                provider="default",
                discovery_endpoint=self.settings.oidc_discovery_endpoint or "",
                client_id=self.settings.oidc_client_id or "",
                client_secret=self.settings.oidc_client_secret or "",
                allowed_domains=list(self.settings.oidc_allowed_domains),
                **redirect,
            )
        except ValidationError as error:
            # Names the setting and the kind of problem, never the value: the
            # input may be the secret, and validator messages can quote it.
            problems = "; ".join(
                f"{'.'.join(str(part) for part in problem['loc'])} ({problem['type']})"
                for problem in error.errors(include_input=False, include_url=False)
            )
            raise ValueError(
                f"The OIDC_* settings cannot be registered: {problems}"
            ) from None

    def _is_migration_eligible(self, federation_config: dict[str, Any]) -> bool:
        if not federation_config:
            return True

        existing_keys = set(federation_config.keys())
        if existing_keys & _FULL_CONFIG_FIELDS:
            return False

        return existing_keys <= _REDIRECT_ONLY_FIELDS


async def run_env_oidc_to_tenant_federation_migration() -> bool:
    settings = get_settings()

    if not settings.federation_enabled:
        logger.debug(
            "Skipping federation startup migration because federation is disabled"
        )
        return False

    if not has_env_oidc_client(settings):
        logger.info(
            "Skipping federation startup migration because OIDC env configuration is incomplete"
        )
        return False

    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))
        service = FederationStartupMigrationService(
            tenant_repo=container.tenant_repo(),
            encryption_service=container.encryption_service(),
            federation_service=container.tenant_federation_service(),
            settings=settings,
        )
        return await service.migrate_env_oidc_to_tenant_federation()
