from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.tables.chat_session_mcp_state_table import ChatSessionMcpState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ChatSessionMcpStateRepo:
    """Persists the server-assigned MCP-protocol ``mcp-session-id`` per
    (chat session, MCP server). Used by ``MCPProxySession`` to resume a
    logical MCP session across user turns.

    The eneo sessionmaker is configured with ``autobegin=False``, and during
    SSE streaming the outer request transaction from
    ``get_session_with_transaction`` is no longer active by the time the
    LLM emits its first tool call (FastAPI tears down yield-style deps when
    the handler returns the StreamingResponse, not when the stream
    finishes). Every other write in the streaming path defends with the
    same "use outer tx if present, else open a short one" pattern (see
    ``SessionService._write_transaction``); this repo does the same.
    """

    def __init__(self, session: "AsyncSession"):
        self.session = session

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield

    async def get(self, chat_session_id: UUID, mcp_server_id: UUID) -> str | None:
        stmt = sa.select(ChatSessionMcpState.mcp_session_id).where(
            ChatSessionMcpState.chat_session_id == chat_session_id,
            ChatSessionMcpState.mcp_server_id == mcp_server_id,
        )
        async with self._tx():
            return await self.session.scalar(stmt)

    async def list_for_chat_session(
        self, chat_session_id: UUID
    ) -> list[tuple[UUID, str]]:
        stmt = sa.select(
            ChatSessionMcpState.mcp_server_id,
            ChatSessionMcpState.mcp_session_id,
        ).where(ChatSessionMcpState.chat_session_id == chat_session_id)
        async with self._tx():
            rows = (await self.session.execute(stmt)).all()
        return [(server_id, session_id) for server_id, session_id in rows]

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
        async with self._tx():
            await self.session.execute(stmt)
