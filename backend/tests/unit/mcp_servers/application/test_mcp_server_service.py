"""Unit tests for MCPServerService auth plumbing.

``_broker_token_provider`` decides how admin-time operations (tool sync,
discovery) authenticate: SSO-scoped servers get a broker-minted token for
the acting admin, exactly like runtime tool calls; static servers keep
using stored credentials.
"""

from types import SimpleNamespace
from uuid import uuid4

from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.application.mcp_token_broker import UserPrincipal
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


class _RecordingBroker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_token(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "minted-token"


def _make_server(auth_scope: str) -> MCPServer:
    return MCPServer(
        tenant_id=uuid4(),
        name="server",
        http_url="https://example.invalid/mcp",
        auth_scope=auth_scope,
    )


def _make_service(broker=None) -> tuple[MCPServerService, SimpleNamespace]:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant=SimpleNamespace(federation_config={"mcp_default_target": "aud"}),
    )
    service = MCPServerService(
        mcp_server_repo=None,
        mcp_server_tool_repo=None,
        user=user,
        mcp_state_repo=None,
        mcp_token_broker=broker,
    )
    return service, user


async def test_broker_token_provider_mints_for_per_user_server():
    broker = _RecordingBroker()
    service, user = _make_service(broker)
    server = _make_server("per_user")

    provider = service._broker_token_provider(server)

    assert provider is not None
    assert await provider() == "minted-token"
    (call,) = broker.calls
    assert call["mcp_server"] is server
    assert call["tenant_federation_config"] == {"mcp_default_target": "aud"}
    assert call["principal"] == UserPrincipal(user=user)


async def test_broker_token_provider_covers_per_tenant_scope():
    broker = _RecordingBroker()
    service, _ = _make_service(broker)

    assert service._broker_token_provider(_make_server("per_tenant")) is not None


def test_broker_token_provider_is_none_for_static_bearer():
    broker = _RecordingBroker()
    service, _ = _make_service(broker)

    assert service._broker_token_provider(_make_server("static_bearer")) is None
    assert broker.calls == []


def test_broker_token_provider_is_none_without_broker():
    service, _ = _make_service(broker=None)

    assert service._broker_token_provider(_make_server("per_user")) is None
