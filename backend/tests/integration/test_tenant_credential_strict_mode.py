"""Integration tests for strict credential resolution edge cases."""

import pytest
from dependency_injector import providers

from intric.main.config import get_settings, set_settings
from intric.settings.credential_resolver import CredentialResolver
from intric.settings.encryption_service import EncryptionService


FERNET_TEST_KEY = "Goxa5kHpfhYh2lLBVmOAXoJ1i8LojRxurx8Wc1SUgL0="


@pytest.mark.integration
@pytest.mark.asyncio
async def test_strict_mode_missing_endpoint_blocks_fallback(db_container):
    """Strict mode raises when a tenant omits required provider fields."""

    base_settings = get_settings()
    strict_settings = base_settings.model_copy()
    strict_settings.tenant_credentials_enabled = True
    strict_settings.encryption_key = FERNET_TEST_KEY
    strict_settings.vllm_model_url = "http://global-vllm"
    set_settings(strict_settings)

    try:
        async with db_container() as container:
            container.encryption_service.override(
                providers.Object(EncryptionService(strict_settings.encryption_key))
            )

            tenant_repo = container.tenant_repo()
            tenants = await tenant_repo.get_all_tenants()
            assert tenants, "Expected seeded tenant in integration database"
            tenant = tenants[0]

            await tenant_repo.update_api_credential(
                tenant_id=tenant.id,
                provider="vllm",
                credential={"api_key": "tenant-vllm-key"},
            )

            updated = await tenant_repo.get(tenant.id)

            container.encryption_service.reset_override()

        resolver = CredentialResolver(
            tenant=updated,
            settings=get_settings(),
            encryption_service=EncryptionService(strict_settings.encryption_key),
        )

        with pytest.raises(ValueError, match="missing required field 'endpoint'"):
            resolver.get_credential_field(
                provider="vllm",
                field="endpoint",
                fallback=strict_settings.vllm_model_url,
            )
    finally:
        set_settings(base_settings)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_tenant_mode_falls_back_to_global_endpoint(db_container):
    """Single-tenant mode continues to fall back to global configuration."""

    base_settings = get_settings()
    fallback_url = "http://shared-vllm"
    single_settings = base_settings.model_copy()
    single_settings.tenant_credentials_enabled = False
    single_settings.vllm_model_url = fallback_url
    single_settings.encryption_key = None
    set_settings(single_settings)

    try:
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenants = await tenant_repo.get_all_tenants()
            assert tenants, "Expected seeded tenant in integration database"
            tenant = tenants[0]

        resolver = CredentialResolver(
            tenant=tenant,
            settings=get_settings(),
            encryption_service=None,
        )

        endpoint = resolver.get_credential_field(
            provider="vllm",
            field="endpoint",
            fallback=fallback_url,
        )

        assert endpoint == fallback_url
    finally:
        set_settings(base_settings)
