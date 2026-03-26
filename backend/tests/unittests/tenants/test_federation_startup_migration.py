from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.settings.credential_resolver import CredentialResolver
from intric.settings.encryption_service import EncryptionService
from intric.tenants.federation_startup_migration import (
    FederationStartupMigrationService,
)
from intric.tenants.tenant import TenantInDB


class MockSettings:
    def __init__(
        self,
        *,
        federation_enabled: bool = True,
        oidc_discovery_endpoint: str | None = "https://idp.example.com/.well-known/openid-configuration",
        oidc_client_id: str | None = "client-id",
        oidc_client_secret: str | None = "super-secret-value",
        oidc_tenant_id: str | None = "tenant-123",
        public_origin: str | None = "https://eneo.example.com",
        strict_oidc_redirect_validation: bool = True,
        encryption_key: str | None = "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs=",
    ):
        self.federation_enabled = federation_enabled
        self.oidc_discovery_endpoint = oidc_discovery_endpoint
        self.oidc_client_id = oidc_client_id
        self.oidc_client_secret = oidc_client_secret
        self.oidc_tenant_id = oidc_tenant_id
        self.public_origin = public_origin
        self.strict_oidc_redirect_validation = strict_oidc_redirect_validation
        self.encryption_key = encryption_key


class FailingEncryptionService:
    def is_active(self) -> bool:
        return True

    def encrypt(self, _plaintext: str) -> str:
        raise ValueError("encrypt failed")


def _make_tenant(*, federation_config=None):
    return TenantInDB(
        id=uuid4(),
        name="Example",
        display_name="Example",
        quota_limit=1000,
        quota_used=0,
        federation_config=federation_config or {},
    )


def _make_service(*, settings=None, tenant=None, encryption_service=None):
    tenant_repo = AsyncMock()
    tenant_repo.get_all_active.return_value = [tenant or _make_tenant()]
    encryption_service = encryption_service or EncryptionService(
        "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs="
    )
    service = FederationStartupMigrationService(
        tenant_repo=tenant_repo,
        encryption_service=encryption_service,
        settings=settings or MockSettings(),
    )
    return service, tenant_repo, encryption_service


@pytest.mark.asyncio
async def test_startup_migration_encrypts_secret_before_persisting():
    service, tenant_repo, _ = _make_service()

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is True
    stored_config = tenant_repo.update_federation_config.await_args.kwargs[
        "federation_config"
    ]
    assert stored_config["client_secret"].startswith("enc:fernet:v1:")
    assert stored_config["provider"] == "default"
    assert stored_config["encrypted_at"]


@pytest.mark.asyncio
async def test_startup_migration_preserves_existing_redirect_fields():
    tenant = _make_tenant(
        federation_config={
            "canonical_public_origin": "https://tenant.example.com",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": [
                "https://external.example.com/auth/callback"
            ],
        }
    )
    service, tenant_repo, _ = _make_service(tenant=tenant)

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is True
    stored_config = tenant_repo.update_federation_config.await_args.kwargs[
        "federation_config"
    ]
    assert stored_config["canonical_public_origin"] == "https://tenant.example.com"
    assert stored_config["redirect_path"] == "/auth/callback"
    assert stored_config["additional_redirect_uris"] == [
        "https://external.example.com/auth/callback"
    ]


def test_tenant_model_canonicalizes_legacy_redirect_path_on_read():
    tenant = _make_tenant(
        federation_config={
            "redirect_path": "/auth/callback?x=1",
        }
    )

    assert tenant.federation_config["redirect_path"] == "/auth/callback"


def test_startup_migration_normalizes_legacy_redirect_path_when_merging_existing_redirect_fields():
    service, _, _ = _make_service()

    merged_config = service._merge_with_existing_redirect_config(
        {"redirect_path": "/auth/callback/"},
        service._build_env_config(),
    )

    assert merged_config["redirect_path"] == "/auth/callback"


@pytest.mark.asyncio
async def test_startup_migration_skips_when_provider_fields_already_exist():
    tenant = _make_tenant(
        federation_config={
            "provider": "auth0",
            "client_id": "existing-client",
            "client_secret": "enc:fernet:v1:existing",
            "discovery_endpoint": "https://existing.example.com/.well-known/openid-configuration",
        }
    )
    service, tenant_repo, _ = _make_service(tenant=tenant)

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is False
    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_migration_skips_when_multiple_active_tenants_exist():
    service, tenant_repo, _ = _make_service()
    tenant_repo.get_all_active.return_value = [_make_tenant(), _make_tenant()]

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is False
    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_migration_skips_when_env_config_is_incomplete():
    settings = MockSettings(oidc_client_secret=None)
    service, tenant_repo, _ = _make_service(settings=settings)

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is False
    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_migration_requires_active_encryption():
    encryption_service = MagicMock()
    encryption_service.is_active.return_value = False
    service, tenant_repo, _ = _make_service(encryption_service=encryption_service)

    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        await service.migrate_env_oidc_to_tenant_federation()

    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_migration_fails_when_encryption_raises():
    service, tenant_repo, _ = _make_service(
        encryption_service=FailingEncryptionService()
    )

    with pytest.raises(ValueError, match="encrypt failed"):
        await service.migrate_env_oidc_to_tenant_federation()

    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_migration_is_idempotent_after_first_run():
    tenant = _make_tenant()
    service, tenant_repo, _ = _make_service(tenant=tenant)

    first_run = await service.migrate_env_oidc_to_tenant_federation()
    stored_config = tenant_repo.update_federation_config.await_args.kwargs[
        "federation_config"
    ]
    tenant.federation_config = stored_config
    tenant_repo.update_federation_config.reset_mock()

    second_run = await service.migrate_env_oidc_to_tenant_federation()

    assert first_run is True
    assert second_run is False
    tenant_repo.update_federation_config.assert_not_awaited()


def test_credential_resolver_can_decrypt_migrated_federation_config():
    encryption_service = EncryptionService(
        "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs="
    )
    tenant = _make_tenant()
    settings = MockSettings()
    service, _, _ = _make_service(
        settings=settings,
        tenant=tenant,
        encryption_service=encryption_service,
    )

    migrated_config = service._merge_with_existing_redirect_config(
        tenant.federation_config,
        service._build_env_config(),
    )
    tenant.federation_config = migrated_config

    resolver = CredentialResolver(
        tenant=tenant,
        settings=settings,
        encryption_service=encryption_service,
    )

    resolved = resolver.get_federation_config()

    assert resolved["client_secret"] == "super-secret-value"
    assert resolved["client_id"] == "client-id"
    assert resolved["discovery_endpoint"] == settings.oidc_discovery_endpoint


@pytest.mark.asyncio
async def test_manual_runner_opens_explicit_transaction(monkeypatch):
    import intric.tenants.federation_startup_migration as startup_migration

    fake_session = MagicMock()

    @asynccontextmanager
    async def fake_session_cm():
        yield fake_session

    @asynccontextmanager
    async def fake_begin_cm():
        yield None

    fake_session.begin.return_value = fake_begin_cm()

    fake_session_manager = MagicMock()
    fake_session_manager.session.return_value = fake_session_cm()

    fake_service = AsyncMock()
    fake_service.migrate_env_oidc_to_tenant_federation.return_value = True
    fake_service_cls = MagicMock(return_value=fake_service)

    monkeypatch.setattr(startup_migration, "get_settings", lambda: MockSettings())
    monkeypatch.setattr(startup_migration, "sessionmanager", fake_session_manager)
    monkeypatch.setattr(startup_migration, "FederationStartupMigrationService", fake_service_cls)

    result = await startup_migration.run_env_oidc_to_tenant_federation_migration()

    assert result is True
    fake_session.begin.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        MockSettings(federation_enabled=False),
        MockSettings(oidc_client_secret=None),
    ],
)
async def test_manual_runner_skips_before_building_encryption_service(
    monkeypatch, settings
):
    import intric.tenants.federation_startup_migration as startup_migration

    encryption_ctor = MagicMock(
        side_effect=AssertionError("EncryptionService should not be constructed")
    )

    monkeypatch.setattr(startup_migration, "get_settings", lambda: settings)
    monkeypatch.setattr(startup_migration, "EncryptionService", encryption_ctor)

    result = await startup_migration.run_env_oidc_to_tenant_federation_migration()

    assert result is False
    encryption_ctor.assert_not_called()
