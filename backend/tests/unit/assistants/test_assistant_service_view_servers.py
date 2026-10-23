"""A tool's view may call tools only on a server one of the user's turns with
the assistant would reach now: one of the assistant's enabled servers within
the space's security classification, the servers a governance policy enforces
in their place, or the provider serving the user for a capability the
assistant has. The provider of a capability is found the same way."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.assistants.assistant_service import AssistantService
from eneo.mcp_servers.application.capability_resolver import CapabilityResolution
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


def _server(**kwargs) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=kwargs.pop("name", "weather"),
        http_url="http://weather.example/mcp",
        **kwargs,
    )


def _service(assistant, *, space_capabilities=(), classification=None, personal=False):
    space = SimpleNamespace(
        get_assistant=lambda assistant_id: assistant,
        security_classification=classification,
        is_personal=lambda: personal,
        enabled_capabilities=list(space_capabilities),
    )
    service = AssistantService.__new__(AssistantService)
    service.user = MagicMock()
    service.repo = MagicMock()
    service.auth_service = MagicMock()
    service.effective_config_service = None
    service.space_repo = MagicMock()
    service.space_repo.get_space_by_assistant = AsyncMock(return_value=space)
    return service


def _assistant(*servers: MCPServer, capabilities=(), is_default=False):
    return SimpleNamespace(
        id=uuid4(),
        mcp_servers=list(servers),
        enabled_capabilities=list(capabilities),
        is_default=is_default,
    )


async def test_server_of_the_assistant_is_reached():
    server = _server()
    assistant = _assistant(server)

    found = await _service(assistant).mcp_server_for_view(
        assistant_id=assistant.id, mcp_server_id=server.id
    )

    assert found is server


async def test_server_the_assistant_does_not_have_is_not_reached():
    assistant = _assistant(_server())

    found = await _service(assistant).mcp_server_for_view(
        assistant_id=assistant.id, mcp_server_id=uuid4()
    )

    assert found is None


async def test_disabled_server_is_not_reached():
    server = _server(is_enabled=False)
    assistant = _assistant(server)

    found = await _service(assistant).mcp_server_for_view(
        assistant_id=assistant.id, mcp_server_id=server.id
    )

    assert found is None


async def test_server_below_the_spaces_classification_is_not_reached():
    server = _server()
    assistant = _assistant(server)
    stricter = MagicMock()
    stricter.is_greater_than.return_value = True

    found = await _service(assistant, classification=stricter).mcp_server_for_view(
        assistant_id=assistant.id, mcp_server_id=server.id
    )

    assert found is None


async def test_enforced_policy_servers_replace_the_assistants_own():
    own, enforced = _server(name="own"), _server(name="enforced")
    assistant = _assistant(own, is_default=True)
    service = _service(assistant, personal=True)
    service.effective_config_service = MagicMock()
    service.effective_config_service.resolve_for = AsyncMock(
        return_value=SimpleNamespace(
            mcp_enforced=True,
            available_mcp_servers=[enforced],
            enabled_capabilities=[],
        )
    )

    assert (
        await service.mcp_server_for_view(
            assistant_id=assistant.id, mcp_server_id=enforced.id
        )
        is enforced
    )
    assert (
        await service.mcp_server_for_view(
            assistant_id=assistant.id, mcp_server_id=own.id
        )
        is None
    )


async def test_provider_serving_the_user_for_an_enabled_capability_is_reached():
    provider = _server(name="search", purpose="web_search")
    assistant = _assistant(capabilities=["web_search", "image_generation"])
    service = _service(assistant, space_capabilities=["web_search"])
    resolve = AsyncMock(
        return_value=CapabilityResolution(
            general_servers=[], capability_servers=[provider]
        )
    )

    with patch("eneo.assistants.assistant_service.resolve_capability_servers", resolve):
        found = await service.mcp_server_for_view(
            assistant_id=assistant.id, mcp_server_id=provider.id
        )

    assert found is provider
    # Only what both the assistant and its space allow is asked for.
    assert resolve.await_args.kwargs["requested_capabilities"] == ["web_search"]


async def test_provider_of_a_capability_is_found_by_its_purpose():
    files = _server(name="Create files", purpose="file_creation")
    assistant = _assistant(_server(), capabilities=["file_creation"])
    service = _service(assistant, space_capabilities=["file_creation"])
    resolve = AsyncMock(
        return_value=CapabilityResolution(
            general_servers=[], capability_servers=[files]
        )
    )

    with patch("eneo.assistants.assistant_service.resolve_capability_servers", resolve):
        found = await service.capability_server(
            assistant_id=assistant.id, purpose="file_creation"
        )
        other = await service.capability_server(
            assistant_id=assistant.id, purpose="web_search"
        )

    assert found is files
    assert other is None


async def test_assistant_without_the_capability_has_no_provider():
    assistant = _assistant(_server())

    found = await _service(assistant).capability_server(
        assistant_id=assistant.id, purpose="file_creation"
    )

    assert found is None
