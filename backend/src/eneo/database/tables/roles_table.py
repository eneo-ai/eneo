from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants


class Roles(BasePublic):
    name: Mapped[str] = mapped_column()
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String))

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # relationships
    tenant: Mapped[Tenants] = relationship()

    __table_args__ = (
        UniqueConstraint("name", "tenant_id", name="roles_name_tenant_unique"),
    )


class PredefinedRoles(BasePublic):
    name: Mapped[str] = mapped_column(unique=True)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String))
