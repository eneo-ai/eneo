# pyright: basic
# FastMCP's Context surface is largely untyped; see foundation.py.
"""Internal (loopback) MCP server for handing a conversation back.

Some turns reach an assistant from another system that has a conversation of
its own with the person: the person chose to talk to the assistant there, and
the assistant holds the conversation until it is returned. This server's one
tool lets the assistant return it. It is attached only to such turns, never to
a turn in Eneo's own interface, where there is nobody to hand back to.

The tool changes nothing in Eneo. Calling it is the signal: the surface that
serves the turn reads the call from the answer's stream and ends its own
stream accordingly. The call carries a reason and nothing else, so no text of
the assistant's reaches the other system as an instruction.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP

from eneo.internal_mcp.constants import HANDBACK_SERVER_NAME
from eneo.internal_mcp.foundation import build_ephemeral_server, internal_tool_context
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

HAND_BACK_TOOL_NAME = "hand_back"
HandbackReason = Literal["declined", "completed"]
HANDBACK_REASONS: tuple[str, ...] = ("declined", "completed")

mcp = FastMCP(
    name="Eneo Conversation Handback",
    stateless_http=True,
    instructions=(
        "One tool for returning the conversation to the system the person is "
        "writing from. It takes a reason and nothing else."
    ),
)

__all__ = [
    "HANDBACK_REASONS",
    "HAND_BACK_TOOL_NAME",
    "build_handback_mcp_server",
    "hand_back",
    "mcp",
]


@mcp.tool()
async def hand_back(reason: HandbackReason, ctx: Context) -> str:
    """Return the conversation to the system the person is writing from.

    The person reached you from another system that has its own assistant.
    You keep the conversation until you return it with this tool. Call it at
    most once in a turn, with one of two reasons:

    - "declined": the question is not yours to answer. It is about something
      you have no knowledge of or access to here, such as the person's own
      calendar, mail or tasks, a colleague's data, or another system. Call the
      tool instead of answering; do not guess, and do not explain at length.
      The other system then answers the person's question itself.
    - "completed": nothing more is expected from you in this conversation.
      Use it only when you have fully answered and the matter is closed, so
      the person's next message should go to the other system. It does NOT
      mean "I have written a reply": if the person may want to follow up with
      you, if you asked them something, or if you are unsure, do not call the
      tool.

    The tool takes no message: anything for the person is written as your
    normal answer.
    """
    # Only a caller Eneo minted this turn's token for; the call itself changes
    # nothing and reads nothing.
    async with internal_tool_context(ctx):
        pass
    if reason == "declined":
        return (
            "The conversation has been returned and the other system will "
            "answer the question. Write nothing more."
        )
    return (
        "Noted: the conversation returns to the other system after this "
        "answer. Finish your answer if it is not complete."
    )


async def build_handback_mcp_server(*, token: str, tenant_id: UUID) -> MCPServer:
    """Build the ephemeral MCP server attached to a turn that can be handed back."""
    return await build_ephemeral_server(
        mcp,
        name=HANDBACK_SERVER_NAME,
        description="Loopback server for returning the conversation to the calling system.",
        token=token,
        tenant_id=tenant_id,
    )
