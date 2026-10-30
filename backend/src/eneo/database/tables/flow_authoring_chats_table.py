"""Human-owned chat bindings; flow definitions remain in the reference schema."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BaseCrossReference
from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class FlowAuthoringChats(BaseCrossReference):
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), primary_key=True
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), unique=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    editing: Mapped[bool] = mapped_column(default=False, server_default="false")
    # The person's own model for the chat; null follows the organisation's
    # default for flow chats, then the space's.
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL"), nullable=True
    )
    reasoning_effort: Mapped[Optional[str]] = mapped_column(nullable=True)
    # When edit mode was last turned on or off.
    mode_changed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "flow_id", name="uq_flow_authoring_chat_owner"
        ),
    )
