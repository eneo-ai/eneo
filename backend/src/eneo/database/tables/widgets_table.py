from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.tables.widget_templates_table import WidgetTemplates


class Widgets(BasePublic):
    # The only identifier that ever appears in a host site's page source.
    public_id: Mapped[str] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))

    # Polymorphic target (assistant today; group chat / app later). No FK by
    # design: the service resolves the target through the space and reports a
    # missing target as an activation blocker instead of cascading.
    target_type: Mapped[str] = mapped_column()
    target_id: Mapped[UUID] = mapped_column()

    status: Mapped[str] = mapped_column(server_default="draft")
    # Bumped on pause/archive and on changes to origins, limits, privacy or
    # bot protection so outstanding visitor tokens stop validating.
    token_generation: Mapped[int] = mapped_column(server_default="0")
    revision: Mapped[int] = mapped_column(server_default="0")

    name: Mapped[str] = mapped_column()
    texts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    limits: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    privacy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    language: Mapped[str] = mapped_column(server_default="auto")
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    bot_protection: Mapped[str] = mapped_column(server_default="altcha")

    # The template the widget follows. The service refuses to delete a
    # template that is still followed; SET NULL is the safety net.
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(WidgetTemplates.id, ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    activated_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("public_id", name="uq_widgets_public_id"),
        Index("ix_widgets_tenant_status", "tenant_id", "status"),
        Index("ix_widgets_space_id", "space_id"),
        Index("ix_widgets_template_id", "template_id"),
        Index("ix_widgets_target", "target_type", "target_id"),
    )
