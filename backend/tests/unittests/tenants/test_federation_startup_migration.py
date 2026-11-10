from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.oidc.sign_in_source import sign_in_config
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.federation_startup_migration import (
    FederationStartupMigrationService,
)
from eneo.tenants.tenant import TenantInDB
from eneo.tenants.tenant_federation_service import TenantFederationService
from tests.fake_oidc_provider import FakeOidcProvider, install

ENCRYPTION_KEY = Fernet.generate_key().decode()
PROVIDER = FakeOidcProvider()


class MockSettings:
    def __init__(
        self,
        *,
        federation_enabled: bool = True,
        oidc_discovery_endpoint: str | None = PROVIDER.discovery_url,
        oidc_client_id: str | None = "client-id",
        oidc_client_secret: str | None = "super-secret-value",
        oidc_tenant_id: str | None = "tenant-123",
        oidc_allowed_domains: list[str] | None = None,
        public_origin: str | None = "https://eneo.example.com",
        strict_oidc_redirect_validation: bool = True,
        encryption_key: str | None = ENCRYPTION_KEY,
    ):
        self.federation_enabled = federation_enabled
        self.oidc_discovery_endpoint = oidc_discovery_endpoint
        self.oidc_client_id = oidc_client_id
        self.oidc_client_secret = oidc_client_secret
        self.oidc_tenant_id = oidc_tenant_id
        self.oidc_allowed_domains = oidc_allowed_domains or []
        self.public_origin = public_origin
        self.strict_oidc_redirect_validation = strict_oidc_redirect_validation
        self.encryption_key = encryption_key


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    """The identity provider the OIDC_* settings point at, served over the
    shared HTTP client the operator door uses for discovery."""
    PROVIDER.down = False
    PROVIDER.requests.clear()
    install(monkeypatch, PROVIDER)
    return PROVIDER


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
    tenant = tenant or _make_tenant()
    tenant_repo = AsyncMock()
    tenant_repo.get_all_active.return_value = [tenant]
    tenant_repo.lock_federation_config.return_value = tenant.federation_config
    encryption_service = encryption_service or EncryptionService(ENCRYPTION_KEY)
    audit_service = AsyncMock()
    service = FederationStartupMigrationService(
        tenant_repo=tenant_repo,
        encryption_service=encryption_service,
        federation_service=TenantFederationService(
            tenant_repo=tenant_repo,
            encryption_service=encryption_service,
            audit_service=audit_service,
        ),
        settings=settings or MockSettings(),
    )
    return service, tenant_repo, audit_service


def _stored(tenant_repo) -> dict:
    return tenant_repo.update_federation_config.await_args.kwargs["federation_config"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reachable", [True, False], ids=["reachable", "unreachable"])
async def test_the_move_stores_the_env_settings_without_contacting_the_provider(
    provider, reachable
):
    provider.down = not reachable
    settings = MockSettings(oidc_allowed_domains=["example.com", "example.org"])
    service, tenant_repo, audit_service = _make_service(settings=settings)

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is True
    stored = _stored(tenant_repo)
    assert stored["provider"] == "default"
    assert stored["discovery_endpoint"] == provider.discovery_url
    assert stored["client_id"] == "client-id"
    assert stored["client_secret"].startswith("enc:fernet:v1:")
    assert stored["encrypted_at"]
    # Who may sign in and be provisioned stays as OIDC_ALLOWED_DOMAINS said.
    assert stored["allowed_domains"] == ["example.com", "example.org"]
    # Sign-in reads the issuer and endpoints from discovery, as env mode did,
    # so the move stores none of them and never fetches the document.
    assert provider.requests == []
    assert not {"issuer", "token_endpoint", "jwks_uri"} & stored.keys()
    # One audited change, like any registration.
    audit_service.log.assert_awaited_once()
    assert (
        audit_service.log.await_args.kwargs["action"] == ActionType.FEDERATION_UPDATED
    )


@pytest.mark.asyncio
async def test_the_audit_names_the_move_not_the_super_api_key():
    service, _, audit_service = _make_service()

    await service.migrate_env_oidc_to_tenant_federation()

    # An operator runs the script on the server; no API key is involved.
    metadata = audit_service.log.await_args.kwargs["metadata"]
    assert metadata["via"] == "env_oidc_migration_script"
    assert metadata["actor"] == {"type": "sysadmin", "via": "env_oidc_migration_script"}


@pytest.mark.asyncio
async def test_the_move_keeps_the_tenants_redirect_settings():
    tenant = _make_tenant(
        federation_config={
            "canonical_public_origin": "https://tenant.example.com",
            "redirect_path": "/auth/callback/",
            "additional_redirect_uris": ["https://external.example.com/auth/callback"],
        }
    )
    service, tenant_repo, _ = _make_service(tenant=tenant)

    migrated = await service.migrate_env_oidc_to_tenant_federation()

    assert migrated is True
    stored = _stored(tenant_repo)
    assert stored["canonical_public_origin"] == "https://tenant.example.com"
    assert stored["redirect_path"] == "/auth/callback"
    assert stored["additional_redirect_uris"] == [
        "https://external.example.com/auth/callback"
    ]


def test_tenant_model_canonicalizes_legacy_redirect_path_on_read():
    tenant = _make_tenant(
        federation_config={
            "redirect_path": "/auth/callback?x=1",
        }
    )

    assert tenant.federation_config["redirect_path"] == "/auth/callback"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "refused_value", "field"),
    [
        ("oidc_client_secret", "s3cr!", "client_secret"),
        ("oidc_allowed_domains", ["not_a_domain-q7x"], "allowed_domains"),
    ],
)
async def test_a_refused_value_stops_the_move_without_echoing_it(
    provider, setting, refused_value, field
):
    settings = MockSettings(**{setting: refused_value})
    service, tenant_repo, _ = _make_service(settings=settings)

    with pytest.raises(ValueError, match=field) as refused:
        await service.migrate_env_oidc_to_tenant_federation()

    echoed = refused_value if isinstance(refused_value, str) else refused_value[0]
    assert echoed not in str(refused.value)
    assert refused.value.__cause__ is None
    assert refused.value.__suppress_context__ is True
    tenant_repo.update_federation_config.assert_not_awaited()
    assert provider.requests == []


@pytest.mark.asyncio
async def test_settings_registered_while_the_move_runs_are_not_overwritten(provider):
    service, tenant_repo, audit_service = _make_service()
    # Another registration lands between the move's first read and its write.
    tenant_repo.lock_federation_config.return_value = {
        "provider": "entra",
        "client_id": "newer-client",
        "client_secret": "enc:fernet:v1:newer",
        "discovery_endpoint": provider.discovery_url,
        "allowed_domains": ["example.org"],
    }

    with pytest.raises(HTTPException) as refused:
        await service.migrate_env_oidc_to_tenant_federation()

    assert refused.value.status_code == 409
    tenant_repo.update_federation_config.assert_not_awaited()
    audit_service.log.assert_not_awaited()


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
async def test_startup_migration_is_idempotent_after_first_run():
    tenant = _make_tenant()
    service, tenant_repo, _ = _make_service(tenant=tenant)

    first_run = await service.migrate_env_oidc_to_tenant_federation()
    tenant.federation_config = _stored(tenant_repo)
    tenant_repo.update_federation_config.reset_mock()

    second_run = await service.migrate_env_oidc_to_tenant_federation()

    assert first_run is True
    assert second_run is False
    tenant_repo.update_federation_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_credential_resolver_can_decrypt_migrated_federation_config():
    tenant = _make_tenant()
    settings = MockSettings()
    service, tenant_repo, _ = _make_service(settings=settings, tenant=tenant)

    await service.migrate_env_oidc_to_tenant_federation()
    tenant.federation_config = _stored(tenant_repo)

    resolved = sign_in_config(settings, tenant, EncryptionService(ENCRYPTION_KEY))

    assert resolved["client_secret"] == "super-secret-value"
    assert resolved["client_id"] == "client-id"
    assert resolved["discovery_endpoint"] == settings.oidc_discovery_endpoint


@pytest.mark.asyncio
async def test_manual_runner_opens_explicit_transaction(monkeypatch):
    import eneo.tenants.federation_startup_migration as startup_migration

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
    monkeypatch.setattr(
        startup_migration, "FederationStartupMigrationService", fake_service_cls
    )

    result = await startup_migration.run_env_oidc_to_tenant_federation_migration()

    assert result is True
    fake_session.begin.assert_called_once_with()
    # The move writes through the same operator service the API uses.
    federation_service = fake_service_cls.call_args.kwargs["federation_service"]
    assert isinstance(federation_service, TenantFederationService)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        MockSettings(federation_enabled=False),
        MockSettings(oidc_client_secret=None),
    ],
)
async def test_manual_runner_skips_before_opening_a_session(monkeypatch, settings):
    import eneo.tenants.federation_startup_migration as startup_migration

    session_manager = MagicMock()
    session_manager.session.side_effect = AssertionError("No session should open")

    monkeypatch.setattr(startup_migration, "get_settings", lambda: settings)
    monkeypatch.setattr(startup_migration, "sessionmanager", session_manager)

    result = await startup_migration.run_env_oidc_to_tenant_federation_migration()

    assert result is False
    session_manager.session.assert_not_called()
