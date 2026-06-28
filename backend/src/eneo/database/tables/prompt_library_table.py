from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class PromptLibrary(BasePublic):
    # __tablename__ is auto-generated as "prompt_library" by BaseWithTableName.

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    text: Mapped[str] = mapped_column()
    current_version: Mapped[int] = mapped_column(Integer, server_default="1")

    # ON DELETE RESTRICT: we want to know who created entries even after the
    # creator leaves the organisation.
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT")
    )

    created_by: Mapped[Users] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_prompt_library_tenant_name"),
    )


class PromptLibraryVersions(BasePublic):
    # __tablename__ is auto-generated as "prompt_library_versions".

    prompt_library_id: Mapped[UUID] = mapped_column(
        ForeignKey(PromptLibrary.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    text: Mapped[str] = mapped_column()
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT")
    )

    prompt_library: Mapped[PromptLibrary] = relationship()
    created_by: Mapped[Users] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "prompt_library_id",
            "version",
            name="uq_prompt_library_versions_entry_version",
        ),
    )
