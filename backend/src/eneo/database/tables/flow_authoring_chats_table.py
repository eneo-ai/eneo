"""Human-owned chat bindings; flow definitions remain in the reference schema."""

from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

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
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "flow_id", name="uq_flow_authoring_chat_owner"
        ),
    )
