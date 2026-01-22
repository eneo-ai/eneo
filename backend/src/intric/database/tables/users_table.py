from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Table, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import Base, BasePublic
from intric.database.tables.roles_table import PredefinedRoles, Roles
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.user_groups_table import UserGroups

if TYPE_CHECKING:
    from intric.database.tables.api_keys_table import ApiKeys


class Users(BasePublic):
    username: Mapped[Optional[str]] = mapped_column()
    email: Mapped[str] = mapped_column(index=True)
    email_verified: Mapped[bool] = mapped_column(server_default="False")
    salt: Mapped[Optional[str]] = mapped_column()
    password: Mapped[Optional[str]] = mapped_column()
    is_active: Mapped[bool] = mapped_column(server_default="True")
    state: Mapped[str] = mapped_column()
    used_tokens: Mapped[int] = mapped_column(default=0)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    quota_limit: Mapped[Optional[int]] = mapped_column(BigInteger)

    tenant: Mapped[Tenants] = relationship()
    api_key: Mapped["ApiKeys"] = relationship(cascade="all, delete-orphan")
    roles: Mapped[list[Roles]] = relationship(
        secondary="users_roles", order_by=Roles.created_at
    )
    predefined_roles: Mapped[list[PredefinedRoles]] = relationship(
        secondary="users_predefined_roles", order_by=PredefinedRoles.created_at
    )
    user_groups: Mapped[list[UserGroups]] = relationship(
        secondary="usergroups_users", viewonly=True
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )

    __table_args__ = (
        Index(
            "idx_unique_active_user_email",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


users_roles_table = Table(
    "users_roles",
    Base.metadata,
    Column("user_id", ForeignKey(Users.id, ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey(Roles.id, ondelete="CASCADE"), primary_key=True),
)

users_predefined_roles_table = Table(
    "users_predefined_roles",
    Base.metadata,
    Column("user_id", ForeignKey(Users.id, ondelete="CASCADE"), primary_key=True),
    Column(
        "predefined_role_id",
        ForeignKey(PredefinedRoles.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)


usergroups_users_table = Table(
    "usergroups_users",
    Base.metadata,
    Column("user_id", ForeignKey(Users.id, ondelete="CASCADE"), primary_key=True),
    Column(
        "user_group_id", ForeignKey(UserGroups.id, ondelete="CASCADE"), primary_key=True
    ),
)
