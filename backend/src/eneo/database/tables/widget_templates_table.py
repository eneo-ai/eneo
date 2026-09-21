from datetime import datetime
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
    # Draft lock groups (TemplateLockGroup values); followers are held to the
    # published copy below.
    locked_groups: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    # The published release: texts, theme, language and locked_groups as of
    # the last publication. NULL until the template is published.
    published: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    published_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
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
