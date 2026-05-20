"""Phase 1 isolation tests for space-private MCP servers (`mcp_servers.space_id`).

Three invariants:

1. The admin catalog endpoint (``GET /api/v1/mcp-servers/``) MUST exclude
   space-private rows. Promoting one through that endpoint would silently
   leak space-scoped servers tenant-wide.
2. The space-scoped list endpoint (``GET /spaces/{id}/mcp-servers/``) MUST
   only return rows whose ``space_id`` matches the URL — even within the
   same tenant. Cross-space leakage in the same tenant is the most likely
   regression and the one the audit log cannot catch.
3. The space-scoped DELETE endpoint MUST refuse to delete a row that
   belongs to a different space, even if the requester is a tenant admin.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.mcp_server_table import MCPServers
from intric.database.tables.spaces_table import Spaces, SpacesUsers
from intric.spaces.api.space_models import SpaceRoleValue


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(default_user)


async def _create_space(client, token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"phase1-mcp-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _insert_space_mcp_row(
    db_container,
    *,
    tenant_id,
    space_id: str | None,
    name: str,
) -> str:
    """Insert an MCP server row directly to bypass the live connection probe.

    The visibility/authz logic under test is independent of whether the
    upstream URL is reachable, so we sidestep ``_test_connection_and_discover_tools``.
    """
    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            sa.insert(MCPServers)
            .values(
                tenant_id=tenant_id,
                space_id=space_id,
                name=name,
                http_url="https://example.invalid/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            .returning(MCPServers.id)
        )
        mcp_id = result.scalar_one()
        await session.commit()
        return str(mcp_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_catalog_excludes_space_private_rows(
    client, db_container, default_user, default_user_token
):
    """``GET /api/v1/mcp-servers/`` must not list space-private rows."""
    space_id = await _create_space(client, default_user_token)
    space_private_id = await _insert_space_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        space_id=space_id,
        name=f"private-{uuid4().hex[:8]}",
    )
    tenant_wide_id = await _insert_space_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        space_id=None,
        name=f"tenant-wide-{uuid4().hex[:8]}",
    )

    response = await client.get(
        "/api/v1/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert tenant_wide_id in ids
    assert space_private_id not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_private_mcp_not_visible_from_other_space_same_tenant(
    client, db_container, default_user, default_user_token
):
    """Cross-space leakage within the same tenant is the silent-failure case."""
    space_a = await _create_space(client, default_user_token)
    space_b = await _create_space(client, default_user_token)
    private_in_a = await _insert_space_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        space_id=space_a,
        name=f"private-a-{uuid4().hex[:8]}",
    )

    response_a = await client.get(
        f"/api/v1/spaces/{space_a}/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response_a.status_code == 200, response_a.text
    assert private_in_a in {item["id"] for item in response_a.json()}

    response_b = await client.get(
        f"/api/v1/spaces/{space_b}/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response_b.status_code == 200, response_b.text
    assert private_in_a not in {item["id"] for item in response_b.json()}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_refuses_cross_space_target(
    client, db_container, default_user, default_user_token
):
    """DELETE must reject if the target row's space_id != path space_id."""
    space_a = await _create_space(client, default_user_token)
    space_b = await _create_space(client, default_user_token)
    private_in_a = await _insert_space_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        space_id=space_a,
        name=f"private-a-{uuid4().hex[:8]}",
    )

    cross_delete = await client.delete(
        f"/api/v1/spaces/{space_b}/mcp-servers/{private_in_a}/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert cross_delete.status_code in (401, 403, 404), cross_delete.text

    same_space_delete = await client.delete(
        f"/api/v1/spaces/{space_a}/mcp-servers/{private_in_a}/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert same_space_delete.status_code == 204, same_space_delete.text

    async with db_container() as container:
        session = container.session()
        remaining = (
            await session.execute(
                sa.select(MCPServers.id).where(MCPServers.id == private_in_a)
            )
        ).scalar_one_or_none()
        assert remaining is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_create_space_mcp(
    client, db_container, default_user, default_user_token
):
    """A space VIEWER must be denied creating an MCP server in the space."""
    space_id = await _create_space(client, default_user_token)

    async with db_container() as container:
        session = container.session()
        user_repo = container.user_repo()
        from intric.users.user import UserAdd, UserState

        viewer = await user_repo.add(
            UserAdd(
                email=f"viewer-{uuid4().hex[:8]}@example.com",
                username=f"viewer_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=default_user.tenant_id,
            )
        )
        await session.execute(
            sa.insert(SpacesUsers).values(
                space_id=space_id,
                user_id=viewer.id,
                role=SpaceRoleValue.VIEWER.value,
            )
        )
        await session.commit()
        auth_service = container.auth_service()
        viewer_token = auth_service.create_access_token_for_user(viewer)

    response = await client.post(
        f"/api/v1/spaces/{space_id}/mcp-servers/",
        json={
            "name": f"denied-{uuid4().hex[:8]}",
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "none",
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code in (401, 403), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_private_row_is_not_visible_to_other_tenant(
    client,
    db_container,
    default_user,
    default_user_token,
    tenant_factory,
    user_factory,
    patch_auth_service_jwt,
):
    """A row owned by tenant A's space must be invisible to tenant B users."""
    space_a = await _create_space(client, default_user_token)
    private_in_a = await _insert_space_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        space_id=space_a,
        name=f"private-tenantA-{uuid4().hex[:8]}",
    )

    async with db_container() as container:
        session = container.session()
        other_tenant = await tenant_factory(session)
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_space = Spaces(
            name=f"tenantB-space-{uuid4().hex[:8]}",
            tenant_id=other_tenant.id,
            user_id=None,
            tenant_space_id=None,
        )
        session.add(other_space)
        await session.flush()
        await session.execute(
            sa.insert(SpacesUsers).values(
                space_id=other_space.id,
                user_id=other_user.id,
                role=SpaceRoleValue.ADMIN.value,
            )
        )
        await session.commit()
        other_space_id = str(other_space.id)
        auth_service = container.auth_service()
        other_user_token = auth_service.create_access_token_for_user(other_user)

    # Tenant B admin listing their own space sees nothing of tenant A's row.
    response = await client.get(
        f"/api/v1/spaces/{other_space_id}/mcp-servers/",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert response.status_code == 200, response.text
    assert private_in_a not in {item["id"] for item in response.json()}

    # Even probing tenant A's space id directly must be rejected, never leak.
    cross_tenant_probe = await client.get(
        f"/api/v1/spaces/{space_a}/mcp-servers/",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert cross_tenant_probe.status_code in (401, 403, 404), cross_tenant_probe.text
