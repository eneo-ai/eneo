from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.database import sessionmanager
from eneo.database.tables.chat_session_mcp_state_table import ChatSessionMcpState
from eneo.database.tables.sessions_table import Sessions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ChatSessionMcpStateRepo:
    """Persists the server-assigned MCP-protocol ``mcp-session-id`` per
    (chat session, MCP server). Used by ``MCPProxySession`` to resume a
    logical MCP session across user turns.

    The eneo sessionmaker is configured with ``autobegin=False``. Writes use a
    short independent transaction. A newly assigned remote protocol session is
    only durable once this row commits; tying it to the request transaction
    could orphan the remote session if later context or model preparation rolls
    that request back.
    """

    def __init__(self, session: "AsyncSession"):
        self.session = session

    @asynccontextmanager
    async def _tx(self) -> AsyncGenerator[None]:
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

    async def claim(
        self,
        chat_session_id: UUID,
        mcp_server_id: UUID,
        candidate_mcp_session_id: str,
        expected_mcp_session_id: str | None,
    ) -> str | None:
        """Commit one protocol-session claimant and return the winning ID.

        A new chat can still belong to the caller's uncommitted request
        transaction. Selecting the parent row in this independent transaction
        makes that case a no-op instead of waiting on, or violating, the
        foreign key. A compare-and-set on ``expected_mcp_session_id`` prevents
        concurrent first turns from both considering their remote ID durable.
        """
        async with sessionmanager.session() as session, session.begin():
            if expected_mcp_session_id is None:
                values = sa.select(
                    Sessions.id,
                    sa.literal(mcp_server_id),
                    sa.literal(candidate_mcp_session_id),
                ).where(Sessions.id == chat_session_id)
                stmt = (
                    pg_insert(ChatSessionMcpState)
                    .from_select(
                        ["chat_session_id", "mcp_server_id", "mcp_session_id"],
                        values,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["chat_session_id", "mcp_server_id"]
                    )
                    .returning(ChatSessionMcpState.mcp_session_id)
                )
                winner = await session.scalar(stmt)
                if winner is not None:
                    return winner
                return await session.scalar(
                    sa.select(ChatSessionMcpState.mcp_session_id).where(
                        ChatSessionMcpState.chat_session_id == chat_session_id,
                        ChatSessionMcpState.mcp_server_id == mcp_server_id,
                    )
                )

            stmt = (
                sa.update(ChatSessionMcpState)
                .where(
                    ChatSessionMcpState.chat_session_id == chat_session_id,
                    ChatSessionMcpState.mcp_server_id == mcp_server_id,
                    ChatSessionMcpState.mcp_session_id == expected_mcp_session_id,
                )
                .values(mcp_session_id=candidate_mcp_session_id)
                .returning(ChatSessionMcpState.mcp_session_id)
            )
            winner = await session.scalar(stmt)
            if winner is not None:
                return winner
            # A missing or changed expected row is an invalidated generation.
            # Never recreate it: an identity-mode toggle owns deletion as the
            # durable boundary between old and new header policy.
            return None

    async def delete_for_server(self, mcp_server_id: UUID) -> None:
        """Invalidate saved protocol sessions in the caller's transaction."""
        stmt = sa.delete(ChatSessionMcpState).where(
            ChatSessionMcpState.mcp_server_id == mcp_server_id
        )
        async with self._tx():
            await self.session.execute(stmt)
