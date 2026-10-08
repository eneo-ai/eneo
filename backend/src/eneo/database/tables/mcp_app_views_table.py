from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.tenant_table import Tenants


class McpAppViews(BasePublic):
    """Cached MCP App view HTML fetched via resources/read.

    Rows are content-addressed on (server, uri, sha256 of the HTML): a
    re-served identical template dedups, a changed template creates a new row
    while old rows keep serving already-rendered messages. The HTML is
    attacker-supplied and must only ever leave the database through the
    mcp-apps content endpoint, which applies the restrictive CSP headers.
    """

    __tablename__ = "mcp_app_views"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "mcp_server_id",
            "uri",
            "content_hash",
            name="uq_mcp_app_views_server_uri_hash",
        ),
        Index("ix_mcp_app_views_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    ui_meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
