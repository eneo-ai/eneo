from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users


class OrgSpaceAssistantRoles(BasePublic):
    """Maps an org-space role slot (e.g. ``prompt_guide``) to the assistant
    currently filling it.

    Tenant scoping is derived via ``org_space_id`` -> ``spaces.tenant_id``;
    no separate ``tenant_id`` column is kept here (PRD §1).
    """

    org_space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="RESTRICT"), nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(
        server_default=true(), default=True, nullable=False
    )
    is_visible_to_users: Mapped[bool] = mapped_column(
        server_default=true(), default=True, nullable=False
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("org_space_id", "kind", name="uq_org_space_roles_kind"),
    )
