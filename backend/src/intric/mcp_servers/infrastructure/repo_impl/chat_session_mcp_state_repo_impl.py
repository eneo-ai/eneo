from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from intric.database.tables.chat_session_mcp_state_table import ChatSessionMcpState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ChatSessionMcpStateRepo:
    """Persists the server-assigned MCP-protocol ``mcp-session-id`` per
    (chat session, MCP server). Used by ``MCPProxySession`` to resume a
    logical MCP session across user turns.
    """

    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def get(self, chat_session_id: UUID, mcp_server_id: UUID) -> str | None:
        stmt = sa.select(ChatSessionMcpState.mcp_session_id).where(
            ChatSessionMcpState.chat_session_id == chat_session_id,
            ChatSessionMcpState.mcp_server_id == mcp_server_id,
        )
        return await self.session.scalar(stmt)

    async def upsert(
        self,
        chat_session_id: UUID,
        mcp_server_id: UUID,
        mcp_session_id: str,
    ) -> None:
        stmt = pg_insert(ChatSessionMcpState).values(
            chat_session_id=chat_session_id,
            mcp_server_id=mcp_server_id,
            mcp_session_id=mcp_session_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["chat_session_id", "mcp_server_id"],
            set_={"mcp_session_id": stmt.excluded.mcp_session_id},
        )
        await self.session.execute(stmt)
