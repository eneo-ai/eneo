"""MCP responses calculate readiness from the persisted tool catalog (#1200)."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)

# The admin tools panel switches a tool per tenant; that setting, not the
# tool's default, is what activation and capability resolution use.
TENANT_TOOL_SETTINGS = {"tenant_disabled": False, "tenant_enabled": True}


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.mark.parametrize(
    "tool_state",
    [
        "approved",
        "disabled",
        "removed",
        "pending",
        "absent",
        *TENANT_TOOL_SETTINGS,
    ],
)
async def test_reads_and_edits_agree_with_settings_and_keep_stored_data(
    client, db_container, admin_user, admin_token, tool_state
):
    async with db_container() as container:
        session = container.session()
        classification = SecurityClassification(
            tenant_id=admin_user.tenant_id,
            name="Readiness regression",
            security_level=1,
        )
        session.add(classification)
        await session.flush()
        classification_id = classification.id
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Readiness regression",
            purpose="web_search",
            http_url="https://example.test/mcp",
            http_auth_type="none",
            is_enabled=False,
            security_classification_id=classification_id,
        )
        session.add(server)
        await session.flush()
        server_id = server.id
        if tool_state != "absent":
            tool = MCPServerTools(
                mcp_server_id=server_id,
                name="search",
                description=None if tool_state == "pending" else "Search",
                input_schema=None if tool_state == "pending" else {"type": "object"},
                pending_description="Awaiting approval",
                requires_approval=True,
                is_enabled_by_default=tool_state not in ("disabled", "tenant_enabled"),
                removed_from_remote=tool_state == "removed",
            )
            session.add(tool)
            await session.flush()
            if tool_state in TENANT_TOOL_SETTINGS:
                session.add(
                    MCPServerToolSettings(
                        tenant_id=admin_user.tenant_id,
                        mcp_server_tool_id=tool.id,
                        is_enabled=TENANT_TOOL_SETTINGS[tool_state],
                    )
                )
        await session.flush()
        # Include pending definitions and timestamps: a server edit must not
        # rewrite, approve or delete any part of its existing tool catalog.
        tool_rows = sa.select(MCPServerTools.__table__).where(
            MCPServerTools.mcp_server_id == server_id
        )
        before = (await session.execute(tool_rows)).mappings().all()

    headers = {"Authorization": f"Bearer {admin_token}"}
    expected = (
        None if tool_state in ("approved", "tenant_enabled") else "no_approved_tools"
    )
    for path in ("/api/v1/mcp-servers/settings/", "/api/v1/mcp-servers/"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        listed = next(
            item for item in response.json()["items"] if item["id"] == str(server_id)
        )
        assert listed["readiness_reason"] == expected

    response = await client.get(f"/api/v1/mcp-servers/{server_id}/", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["readiness_reason"] == expected

    # A separate request/session avoids a list read masking missing eager loads.
    response = await client.post(
        f"/api/v1/mcp-servers/{server_id}/",
        json={"name": "Renamed source"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed source"
    assert response.json()["readiness_reason"] == expected

    response = await client.put(
        f"/api/v1/mcp-servers/settings/{server_id}/",
        json={"env_vars": {}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["readiness_reason"] == expected

    response = await client.post(
        f"/api/v1/mcp-servers/{server_id}/deactivate/", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["readiness_reason"] == expected

    async with db_container() as container:
        session = container.session()
        after = (await session.execute(tool_rows)).mappings().all()
        assert after == before
        # None of these edits names a classification, so each must keep it.
        assert (
            await session.scalar(
                sa.select(MCPServers.security_classification_id).where(
                    MCPServers.id == server_id
                )
            )
            == classification_id
        )


@pytest.mark.parametrize("activate", [False, True])
async def test_create_and_activation_responses_include_discovered_tools(
    client, db_container, admin_token, monkeypatch, activate
):
    # Only the external MCP connection is replaced; persistence and HTTP
    # response assembly use the real application and PostgreSQL repositories.
    monkeypatch.setattr(
        MCPServerService,
        "_test_connection_and_discover_tools",
        AsyncMock(
            return_value=(
                [
                    {
                        "name": "search",
                        "description": "Search",
                        "input_schema": {"type": "object"},
                    }
                ],
                ConnectionResult(success=True),
            )
        ),
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": "New source",
            "purpose": "web_search",
            "http_url": "https://example.test/mcp",
            "activate": activate,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    created = response.json()["server"]
    assert created["readiness_reason"] is None
    assert created["is_enabled"] is activate
    server_id = created["id"]

    response = await client.post(
        f"/api/v1/mcp-servers/{server_id}/activate/", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["server"]["readiness_reason"] is None

    response = await client.post(
        f"/api/v1/mcp-servers/{server_id}/deactivate/", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["readiness_reason"] is None
    assert response.json()["is_enabled"] is False

    async with db_container() as container:
        tools = await container.mcp_server_tool_repo().by_server(UUID(server_id))
        assert len(tools) == 1
        assert tools[0].name == "search"
        assert tools[0].is_enabled_by_default is True
