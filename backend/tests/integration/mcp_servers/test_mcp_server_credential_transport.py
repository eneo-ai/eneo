"""The MCP server API refuses a credential bound for a plain-http address."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from eneo.database.tables.mcp_server_table import MCPServers
from eneo.main.exceptions import ErrorCodes


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


# Kills: the refusal surfacing as anything but the API's 400 validation shape
# (a 502 from the connection test, a 500), and a row being saved anyway.
async def test_create_with_a_bearer_token_on_plain_http_is_a_400(
    client, db_container, admin_token
):
    name = f"plain-http-{uuid4().hex[:8]}"

    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": name,
            "http_url": "http://mcp.example.org/mcp",
            "http_auth_type": "bearer",
            "http_auth_config_schema": {"token": "sk-secret"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["eneo_error_code"] == ErrorCodes.BAD_REQUEST
    assert body["code"] == "mcp_credential_requires_https"
    assert "sk-secret" not in response.text
    async with db_container() as container:
        saved = await container.session().scalar(
            select(MCPServers.id).where(MCPServers.name == name)
        )
    assert saved is None
