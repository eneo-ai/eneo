from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from intric.database.database import sessionmanager
from intric.main.config import (
    Settings,
    canonicalize_legacy_redirect_path,
    get_settings,
    validate_redirect_path,
)
from intric.main.logging import get_logger
from intric.settings.encryption_service import EncryptionService
from intric.tenants.tenant_repo import TenantRepository

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
        settings: Settings,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.encryption_service = encryption_service
        self.settings = settings

    async def migrate_env_oidc_to_tenant_federation(self) -> bool:
        if not self.settings.federation_enabled:
            logger.debug(
                "Skipping federation startup migration because federation is disabled"
            )
            return False

        if not self._has_complete_env_config():
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

        env_config = self._build_env_config()
        merged_config = self._merge_with_existing_redirect_config(
            tenant.federation_config,
            env_config,
        )
        await self.tenant_repo.update_federation_config(
            tenant_id=tenant.id,
            federation_config=merged_config,
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

    def _has_complete_env_config(self) -> bool:
        return bool(
            self.settings.oidc_discovery_endpoint
            and self.settings.oidc_client_id
            and self.settings.oidc_client_secret
        )

    def _build_env_config(self) -> dict[str, Any]:
        client_secret = self.settings.oidc_client_secret
        if client_secret is None:
            raise ValueError(
                "OIDC client secret is required for federation startup migration"
            )

        encrypted_secret = self.encryption_service.encrypt(client_secret)
        now = datetime.now(timezone.utc).isoformat()

        config: dict[str, Any] = {
            "provider": "default",
            "discovery_endpoint": self.settings.oidc_discovery_endpoint,
            "client_id": self.settings.oidc_client_id,
            "client_secret": encrypted_secret,
            "scopes": ["openid", "email", "profile"],
            "encrypted_at": now,
        }
        if self.settings.oidc_tenant_id:
            config["tenant_id"] = self.settings.oidc_tenant_id

        return config

    def _is_migration_eligible(self, federation_config: dict[str, Any]) -> bool:
        if not federation_config:
            return True

        existing_keys = set(federation_config.keys())
        if existing_keys & _FULL_CONFIG_FIELDS:
            return False

        return existing_keys <= _REDIRECT_ONLY_FIELDS

    def _merge_with_existing_redirect_config(
        self,
        existing_config: dict[str, Any],
        env_config: dict[str, Any],
    ) -> dict[str, Any]:
        merged_config = dict(env_config)
        for field in _REDIRECT_ONLY_FIELDS:
            if field not in existing_config:
                continue

            value = existing_config[field]
            if field == "redirect_path" and isinstance(value, str):
                value = validate_redirect_path(canonicalize_legacy_redirect_path(value))

            merged_config[field] = value
        return merged_config


async def run_env_oidc_to_tenant_federation_migration() -> bool:
    settings = get_settings()

    if not settings.federation_enabled:
        logger.debug(
            "Skipping federation startup migration because federation is disabled"
        )
        return False

    if not (
        settings.oidc_discovery_endpoint
        and settings.oidc_client_id
        and settings.oidc_client_secret
    ):
        logger.info(
            "Skipping federation startup migration because OIDC env configuration is incomplete"
        )
        return False

    encryption_service = EncryptionService(settings)

    async with sessionmanager.session() as session, session.begin():
        tenant_repo = TenantRepository(
            session=session,
            encryption_service=encryption_service,
        )
        service = FederationStartupMigrationService(
            tenant_repo=tenant_repo,
            encryption_service=encryption_service,
            settings=settings,
        )
        return await service.migrate_env_oidc_to_tenant_federation()
