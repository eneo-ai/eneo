"""Disconnecting a connection through the real HTTP handler and service."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient

from eneo.main.container.container import Container


async def disconnect(case, authenticated_integration_app, integration_id):
    audit_service = AsyncMock()
    container = Container(
        user=providers.Object(case.user),
        user_integration_service=providers.Object(case.service),
        user_integration_repo=providers.Object(case.integration_repo),
        audit_service=providers.Object(audit_service),
    )
    app = authenticated_integration_app(container)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/integrations/users/{integration_id}/")
    return response, audit_service


async def test_owner_disconnects_own_connection(
    integration_access, authenticated_integration_app
):
    case = integration_access
    response, audit_service = await disconnect(
        case, authenticated_integration_app, case.integration.id
    )
    assert response.status_code == 204, response.text
    case.integration_repo.one.assert_awaited_once_with(
        id=case.integration.id, tenant_id=case.user.tenant_id
    )
    case.integration_repo.remove.assert_awaited_once_with(id=case.integration.id)
    audit_service.log_async.assert_awaited_once()


@pytest.mark.parametrize("target", ["other_user", "foreign_tenant", "unknown"])
async def test_inaccessible_connections_are_indistinguishable(
    integration_access, authenticated_integration_app, target
):
    case = integration_access
    integration_id = case.integration.id
    if target == "other_user":
        case.integration.user_id = uuid4()
    elif target == "foreign_tenant":
        case.integration.user_id = uuid4()
        case.integration.tenant_integration.tenant_id = uuid4()
    else:
        integration_id = uuid4()

    response, audit_service = await disconnect(
        case, authenticated_integration_app, integration_id
    )
    assert response.status_code == 404, response.text
    assert response.json()["message"] == "Not found"
    case.integration_repo.remove.assert_not_awaited()
    audit_service.log_async.assert_not_awaited()


async def test_organization_connection_is_not_disconnected_here(
    integration_access, authenticated_integration_app
):
    case = integration_access
    case.use_organization_connection()
    response, audit_service = await disconnect(
        case, authenticated_integration_app, case.integration.id
    )
    assert response.status_code == 403, response.text
    case.integration_repo.remove.assert_not_awaited()
    audit_service.log_async.assert_not_awaited()
