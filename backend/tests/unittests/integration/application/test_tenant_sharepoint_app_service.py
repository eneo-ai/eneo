"""Credential changes must not leave a token minted with the old secret in cache."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.application.tenant_sharepoint_app_service import (
    TenantSharePointAppService,
)
from eneo.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp


def _existing_app() -> TenantSharePointApp:
    now = datetime.now(timezone.utc)
    return TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client",
        client_secret="old-secret",
        tenant_domain="contoso.onmicrosoft.com",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def service():
    repo = AsyncMock()
    app = _existing_app()
    repo.get_by_tenant.return_value = app
    repo.update.side_effect = lambda obj: obj
    cache = MagicMock()
    return TenantSharePointAppService(repo, tenant_app_auth_service=cache), app, cache


async def test_rotating_the_secret_forgets_the_cached_token(service):
    svc, app, cache = service

    await svc.configure_tenant_app(
        tenant_id=app.tenant_id,
        client_id="client",
        client_secret="new-secret",
        tenant_domain="contoso.onmicrosoft.com",
        created_by=uuid4(),
    )

    cache.clear_cache.assert_called_once_with(str(app.id))


async def test_switching_to_a_service_account_forgets_the_cached_token(service):
    svc, app, cache = service

    await svc.configure_service_account(
        tenant_id=app.tenant_id,
        client_id="client",
        client_secret="new-secret",
        tenant_domain="contoso.onmicrosoft.com",
        refresh_token="refresh",
        service_account_email="svc@contoso.com",
        created_by=uuid4(),
    )

    cache.clear_cache.assert_called_once_with(str(app.id))


@pytest.mark.parametrize("action", ["deactivate_app", "delete_app"])
async def test_shutting_the_app_off_forgets_the_cached_token(service, action):
    svc, app, cache = service

    await getattr(svc, action)(app.tenant_id)

    cache.clear_cache.assert_called_once_with(str(app.id))


async def test_creating_a_new_app_has_nothing_to_forget(service):
    svc, app, cache = service
    svc.tenant_app_repo.get_by_tenant.return_value = None
    svc.tenant_app_repo.create.side_effect = lambda obj: obj

    await svc.configure_tenant_app(
        tenant_id=uuid4(),
        client_id="client",
        client_secret="secret",
        tenant_domain="contoso.onmicrosoft.com",
        created_by=uuid4(),
    )

    cache.clear_cache.assert_not_called()
