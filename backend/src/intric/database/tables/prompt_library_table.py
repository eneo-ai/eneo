from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class PromptLibrary(BasePublic):
    # __tablename__ is auto-generated as "prompt_library" by BaseWithTableName.

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    text: Mapped[str] = mapped_column()

    # ON DELETE RESTRICT: we want to know who created entries even after the
    # creator leaves the organisation.
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT")
    )

    created_by: Mapped[Users] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_prompt_library_tenant_name"),
    )
