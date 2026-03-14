from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants


class AllowedOrigins(BasePublic):
    url: Mapped[str] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "url",
            name="uq_allowed_origins_tenant_url",
        ),
    )
