from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import TIMESTAMP, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import BasePublic
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class HelpAssistantRuns(BasePublic):
    """Canonical record of a single help-assistant run.

    One-to-one with a ``sessions`` row (``session_id`` UNIQUE): each helper
    invocation produces exactly one row here. ``tenant_id`` is explicit
    (PRD §6) because retention sweeps and every list/read path on this table
    are hot — the redundancy avoids joining via ``spaces.tenant_id`` on
    those queries. ``target_id`` carries no FK so the row survives target
    deletion for audit; identity is preserved in the underlying session and
    in admin history. ``assistant_id`` and ``actor_user_id`` are
    ``ON DELETE SET NULL`` to survive helper-archival or user removal.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True, nullable=False
    )
    org_space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL"), nullable=True
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="in_progress", nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_help_assistant_runs_session_id"),
        Index(
            "ix_help_assistant_runs_tenant_created_at",
            "tenant_id",
            text("created_at DESC"),
        ),
    )
