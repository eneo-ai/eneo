from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class WidgetTemplates(BasePublic):
    """An organisation's house style for widgets: texts and appearance that
    editors copy onto a new widget. A snapshot, never a live link."""

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    name: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column(server_default="")
    texts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    language: Mapped[str] = mapped_column(server_default="auto")
    is_default: Mapped[bool] = mapped_column(server_default=sa.false())
    # TemplateLockGroup values the linked widgets follow.
    locked_groups: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_widget_templates_tenant_id", "tenant_id"),
        Index(
            "uq_widget_templates_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("is_default"),
        ),
    )
