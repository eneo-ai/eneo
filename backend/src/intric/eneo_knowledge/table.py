from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BaseWithTableName, IdMixin
from intric.database.tables.tenant_table import Tenants


class KnowledgeSources(IdMixin, BaseWithTableName):
    """Ownership map for proxied eneo-knowledge collections.

    Each row links a tenant + space (in eneo) to a slug owned by the shared
    single-tenant eneo-knowledge instance, and to the backing
    ``mcp_servers`` row (space-scoped) that assistants pick up via the
    Phase 1 visibility query. Rows are immutable once written — there is
    no update path, only create and delete — so we deliberately omit
    ``updated_at``.
    """

    __tablename__ = "knowledge_sources"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "eneo_knowledge_slug",
            name="uq_knowledge_sources_tenant_slug",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    eneo_knowledge_slug: Mapped[str] = mapped_column(Text, nullable=False)
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
