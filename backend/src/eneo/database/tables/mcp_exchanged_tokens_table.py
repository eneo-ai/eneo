from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.tenant_table import Tenants


class MCPExchangedTokens(BasePublic):
    """Short-lived audience-bound tokens minted by the MCP token broker.

    Cache-only, safe to truncate. One row per
    ``(mcp_server_id, subject_type, subject_id)``. ``subject_id`` points
    at a user or a tenant; no FK because the column targets two tables.
    Cascades come from ``mcp_server_id`` (server delete) and
    ``tenant_id`` (tenant delete).
    """

    __tablename__ = "mcp_exchanged_tokens"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "mcp_server_id",
            "subject_type",
            "subject_id",
            name="uq_mcp_exchanged_tokens_server_subject",
        ),
        Index("ix_mcp_exchanged_tokens_tenant_id", "tenant_id"),
    )

    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(
        PgEnum(
            "user",
            "tenant",
            name="mcp_exchanged_token_subject_type",
            create_type=False,
        ),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    idp_issuer: Mapped[str] = mapped_column(Text, nullable=False)
