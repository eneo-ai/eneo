from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants


class Roles(BasePublic):
    name: Mapped[str] = mapped_column()
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    predefined_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # relationships
    tenant: Mapped[Tenants] = relationship(foreign_keys=[tenant_id])

    __table_args__ = (
        UniqueConstraint("name", "tenant_id", name="roles_name_tenant_unique"),
    )
