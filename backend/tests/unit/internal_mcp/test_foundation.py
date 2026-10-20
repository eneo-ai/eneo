from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from eneo.authentication.auth_service import AuthService
from eneo.internal_mcp.foundation import (
    ToolContext,
    build_ephemeral_server,
    session_id_from_token,
)
from tests.fixtures import TEST_USER


async def test_ephemeral_loopback_server_is_marked_internal():
    """The loopback factory is the only place that sets ``is_internal``: it is
    what distinguishes Eneo's own tools from an external server that happens
    to carry the same name."""
    server = await build_ephemeral_server(
        FastMCP("knowledge"),
        name="knowledge",
        description="Loopback",
        token="token",
        tenant_id=uuid4(),
    )

    assert server.is_internal is True
    assert server.name == "knowledge"


def test_scoped_token_carries_the_session_id_only_when_minted_for_one():
    """A tool that creates something during a conversation binds it to the
    session named by the token; a token minted outside one names none."""
    session_id = uuid4()
    in_session = AuthService().create_scoped_mcp_token(
        TEST_USER, assistant_id=uuid4(), session_id=session_id
    )
    outside = AuthService().create_scoped_mcp_token(TEST_USER, assistant_id=uuid4())

    assert session_id_from_token(in_session) == session_id
    assert session_id_from_token(outside) is None


def test_tool_context_defaults_to_no_session():
    context = ToolContext(container=object(), user=object(), assistant_id=uuid4())

    assert context.session_id is None
