from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import BasePublic
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users


class HelpAssistantAssignmentHistory(BasePublic):
    """Append-only audit trail for help-assistant role reassignments.

    Rows are written by the service layer whenever the assistant filling a
    role slot is reset, reassigned, or unassigned. ``assistant_id`` and
    ``replaced_by_assistant_id`` are ``ON DELETE SET NULL`` so the
    "archive replaced helpers" admin action can hard-delete the underlying
    assistant rows while keeping the history intact;
    ``assistant_name_snapshot`` retains identity. Tenant scoping derives via
    ``org_space_id`` -> ``spaces.tenant_id``; no separate ``tenant_id``
    column (PRD §3).
    """

    org_space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL"), nullable=True
    )
    assistant_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    replaced_by_assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    replaced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_help_assistant_assignment_history_lookup",
            "org_space_id",
            "kind",
            text("replaced_at DESC"),
        ),
    )
