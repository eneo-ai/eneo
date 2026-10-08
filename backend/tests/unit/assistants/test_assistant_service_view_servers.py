"""Native document exports resolve the provider serving this assistant and user."""

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
