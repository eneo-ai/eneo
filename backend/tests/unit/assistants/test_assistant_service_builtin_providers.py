"""Built-in capability providers reach the proxy with a per-completion token and
the loopback server's live tool definitions."""

from unittest.mock import MagicMock
from uuid import uuid4

from eneo.assistants.assistant_service import AssistantService
from eneo.mcp_servers.domain.entities.mcp_server import INTERNAL_AUTH_TYPE, MCPServer


def _service(token: str = "scoped-token") -> AssistantService:
    service = AssistantService.__new__(AssistantService)
    service.user = MagicMock()
    service.auth_service = MagicMock()
    service.auth_service.create_scoped_mcp_token.return_value = token
    return service


def _provider(**kwargs) -> MCPServer:
    return MCPServer(
        tenant_id=uuid4(),
        name="Image generation",
        http_url="http://backend/internal-mcp/image_generation/mcp",
        purpose="image_generation",
        **kwargs,
    )


def _builtin_provider() -> MCPServer:
    return _provider(
        http_auth_type=INTERNAL_AUTH_TYPE,
        image_model_id=uuid4(),
    )


async def test_builtin_provider_is_authenticated_with_a_token_naming_its_row():
    service = _service()
    server = _builtin_provider()
    assistant_id = uuid4()

    authenticated = await service._with_builtin_provider_token(
        server, assistant_id=assistant_id
    )

    assert authenticated.http_auth_config_schema == {"token": "scoped-token"}
    assert authenticated.http_auth_type == INTERNAL_AUTH_TYPE
    assert authenticated.id == server.id
    service.auth_service.create_scoped_mcp_token.assert_called_once_with(
        service.user, assistant_id=assistant_id, mcp_server_id=server.id
    )


async def test_persisted_builtin_provider_entity_never_carries_the_token():
    service = _service()
    server = _builtin_provider()

    authenticated = await service._with_builtin_provider_token(
        server, assistant_id=uuid4()
    )

    assert authenticated is not server
    assert server.http_auth_config_schema is None


async def test_external_provider_passes_through_unchanged():
    service = _service()
    server = _provider(
        http_auth_type="bearer", http_auth_config_schema={"token": "encrypted"}
    )

    assert (
        await service._with_builtin_provider_token(server, assistant_id=uuid4())
        is server
    )
    service.auth_service.create_scoped_mcp_token.assert_not_called()


async def test_builtin_provider_carries_live_tool_definitions():
    service = _service()
    server = _builtin_provider()

    authenticated = await service._with_builtin_provider_token(
        server, assistant_id=uuid4()
    )

    assert [tool.name for tool in authenticated.tools] == ["generate_image"]
    assert "reference_images" in authenticated.tools[0].input_schema["properties"]
    # The persisted entity keeps its snapshot; only the per-completion copy is live.
    assert server.tools == []
