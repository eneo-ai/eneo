"""The public selector offers configured tenants without changing login modes."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from eneo.authentication import federation_router as routes
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.tenants.tenant import TenantInDB


def configured_idp(**overrides: str) -> dict[str, str]:
    return {
        "provider": "oidc",
        "client_id": "public-client-id",
        "client_secret": "unused-test-value",
        "discovery_endpoint": "https://idp.example/.well-known/openid-configuration",
        **overrides,
    }


def tenant(slug: str | None, config: dict[str, str]) -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name=slug or "No slug",
        slug=slug,
        quota_limit=1024,
        federation_config=config,
    )


@pytest.fixture
def discovery(monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Mock]:
    settings = get_settings().model_copy(update={"federation_enabled": True})
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    container = Mock(spec=Container)
    container.tenant_repo.return_value.get_all_active = AsyncMock()
    return settings, container


@pytest.mark.asyncio
@pytest.mark.parametrize("federation_enabled", [True, False])
async def test_selector_filters_only_in_federation_mode(
    discovery: tuple[Settings, Mock], federation_enabled: bool
) -> None:
    settings, container = discovery
    settings.federation_enabled = federation_enabled
    tenants = [
        tenant("ready", configured_idp()),
        tenant("no-idp", {}),
        tenant("redirect-only", {"canonical_public_origin": "https://tenant.example"}),
        tenant("empty-client", configured_idp(client_id="")),
        tenant("empty-discovery", configured_idp(discovery_endpoint="")),
        tenant(None, configured_idp()),
    ]
    tenants[0].display_name = "Ready organisation"
    container.tenant_repo.return_value.get_all_active.return_value = tenants

    result = await routes.list_tenants(container)

    expected = ["ready"] if federation_enabled else [t.slug for t in tenants if t.slug]
    assert [t.slug for t in result.tenants] == expected
    assert result.tenants[0].model_dump() == {
        "slug": "ready",
        "name": "ready",
        "display_name": "Ready organisation",
    }
    container.tenant_repo.return_value.get_all_active.assert_awaited_once()

    status = await routes.get_federation_status(container)
    assert status.tenant_count == len(tenants)
    assert status.has_multi_tenant_federation is federation_enabled
    assert status.has_single_tenant_federation is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,expected",
    [
        (configured_idp(), True),
        ({}, False),
        ({"canonical_public_origin": "https://tenant.example"}, False),
        (configured_idp(client_id=""), False),
        (configured_idp(discovery_endpoint=""), False),
    ],
)
async def test_single_tenant_status_uses_the_same_configuration_requirement(
    discovery: tuple[Settings, Mock], config: dict[str, str], expected: bool
) -> None:
    _, container = discovery
    # Single-tenant initiation resolves the tenant without a slug.
    container.tenant_repo.return_value.get_all_active.return_value = [
        tenant(None, config)
    ]

    status = await routes.get_federation_status(container)

    assert status.tenant_count == 1
    assert status.has_single_tenant_federation is expected
    assert status.has_multi_tenant_federation is False


@pytest.mark.asyncio
async def test_no_active_tenants_has_no_selector_or_single_tenant_flow(
    discovery: tuple[Settings, Mock],
) -> None:
    _, container = discovery
    container.tenant_repo.return_value.get_all_active.return_value = []

    assert (await routes.list_tenants(container)).tenants == []
    status = await routes.get_federation_status(container)
    assert status.tenant_count == 0
    assert status.has_single_tenant_federation is False
    assert status.has_multi_tenant_federation is False
