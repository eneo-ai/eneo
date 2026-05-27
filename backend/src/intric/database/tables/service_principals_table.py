from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class ServicePrincipals(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE", name="fk_service_principals_tenant"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    scope_type: Mapped[str] = mapped_column(nullable=False)
    scope_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(nullable=False, server_default="active")
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="SET NULL",
            name="fk_service_principals_created_by_user",
        ),
        nullable=True,
    )
    disabled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('active', 'disabled')",
            name="ck_service_principals_state",
        ),
        sa.CheckConstraint(
            "("
            "(state = 'active' AND disabled_at IS NULL) "
            "OR "
            "(state = 'disabled' AND disabled_at IS NOT NULL)"
            ")",
            name="ck_service_principals_disabled_at_matches_state",
        ),
        sa.Index("ix_service_principals_tenant_id", "tenant_id"),
    )
