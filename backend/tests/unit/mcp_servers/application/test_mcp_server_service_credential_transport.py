"""Registration refuses a credentialed MCP server on a plain-http address."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.mcp_servers.application.mcp_server_service import (
    MCPServerCredentialTransportError,
    MCPServerService,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


def _service(stored: MCPServer | None = None) -> MCPServerService:
    user = MagicMock()
    user.tenant_id = uuid4()
    user.permissions = ["admin"]
    repo = AsyncMock()
    service = MCPServerService(
        mcp_server_repo=repo, mcp_server_tool_repo=AsyncMock(), user=user
    )
    if stored is not None:
        stored.tenant_id = user.tenant_id
        repo.one.return_value = stored
    # Fails the test if the rule lets a request reach the network.
    service._test_connection_and_discover_tools = AsyncMock(
        side_effect=AssertionError("connection attempted")
    )
    return service


# Kills: no check on create, or a check placed after the connection test (the
# token would already have been sent over http).
async def test_create_refuses_a_credential_on_plain_http_before_connecting():
    service = _service()

    with pytest.raises(MCPServerCredentialTransportError):
        await service.create_mcp_server(
            name="Legacy",
            http_url="http://mcp.example.org/mcp",
            http_auth_type="bearer",
            http_auth_config_schema={"token": "sk-secret"},
        )

    service.repo.add.assert_not_called()


# Kills: validating only the fields a request names instead of the final state
# (stored URL + new auth type, new URL + stored auth type, or both new).
@pytest.mark.parametrize(
    ("stored_url", "stored_auth", "change"),
    [
        (
            "https://mcp.example.org/mcp",
            "bearer",
            {"http_url": "http://mcp.example.org/mcp"},
        ),
        (
            "http://mcp.example.org/mcp",
            "none",
            {"http_auth_type": "bearer", "http_auth_config_schema": {"token": "sk"}},
        ),
        (
            "https://mcp.example.org/mcp",
            "none",
            {
                "http_url": "http://mcp.example.org/mcp",
                "http_auth_type": "api_key_header",
                "http_auth_config_schema": {"header_name": "X-Api-Key", "token": "sk"},
            },
        ),
    ],
)
async def test_update_refuses_a_final_state_that_sends_a_credential_over_http(
    stored_url, stored_auth, change
):
    stored = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Server",
        http_url=stored_url,
        http_auth_type=stored_auth,
        http_auth_config_schema={"token": "stored"} if stored_auth != "none" else None,
    )
    service = _service(stored)

    with pytest.raises(MCPServerCredentialTransportError):
        await service.update_mcp_server(stored.id, **change)

    service.repo.update.assert_not_called()
