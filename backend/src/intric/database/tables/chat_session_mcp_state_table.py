from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BaseCrossReference
from intric.database.tables.mcp_server_table import MCPServers
from intric.database.tables.sessions_table import Sessions


class ChatSessionMcpState(BaseCrossReference):
    """Persists the server-assigned MCP-protocol ``mcp-session-id`` for a
    given (chat session, MCP server) pair so a later user turn (which opens a
    fresh ``streamablehttp_client``) can resume the same logical MCP session.
    """

    __tablename__ = "chat_session_mcp_state"  # type: ignore[assignment]

    chat_session_id: Mapped[UUID] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_session_id: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_chat_session_mcp_state_mcp_server_id", "mcp_server_id"),
    )
