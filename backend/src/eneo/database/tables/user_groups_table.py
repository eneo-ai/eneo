from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.base_class import BasePublic

if TYPE_CHECKING:
    from eneo.database.tables.tenant_table import Tenants
    from eneo.database.tables.users_table import Users


class UserGroups(BasePublic):
    name: Mapped[str] = mapped_column()
    external_id: Mapped[Optional[str]] = mapped_column(index=True)
    state: Mapped[Optional[str]] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )

    # relationships
    tenant: Mapped["Tenants"] = relationship()
    users: Mapped[list["Users"]] = relationship(secondary="usergroups_users")

    __table_args__ = (
        Index(
            "user_groups_name_tenant_unique",
            "name",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("state IS NULL OR state != 'deleted'"),
        ),
    )
