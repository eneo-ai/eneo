from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.service_table import Services
from eneo.database.tables.users_table import Users
from eneo.database.tables.widgets_table import Widgets

if TYPE_CHECKING:
    from eneo.database.tables.questions_table import Questions


class Sessions(BasePublic):
    # A session belongs to exactly one principal: a person (user_id), the
    # service principal behind a service key (service_principal_id), or a
    # widget visitor (widget_id + visitor_id).
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True
    )
    service_principal_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            ServicePrincipals.id,
            ondelete="RESTRICT",
            name="fk_sessions_service_principal",
        ),
        nullable=True,
    )
    # The key that started a service principal's session. A trace, not the
    # owner: the key changes on rotation and may be removed.
    api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ApiKeysV2.id, ondelete="SET NULL"), nullable=True
    )
    # Widget sessions: the principal is the widget plus a pseudonymous
    # visitor id; neither a user nor an API key is involved.
    widget_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Widgets.id, ondelete="CASCADE"), nullable=True
    )
    visitor_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column()
    feedback_value: Mapped[Optional[int]] = mapped_column()
    feedback_text: Mapped[Optional[str]] = mapped_column()
    # When the name and the feedback text were last written: conversation
    # history removes each once its own time is older than the period.
    name_set_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    feedback_set_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    # Raised by the question removal trigger: an answer generated from history
    # read at an older revision may hold removed turns, so its log is cleared.
    history_revision: Mapped[int] = mapped_column(server_default=sa.text("0"))

    # Foreign keys
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE")
    )
    service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Services.id, ondelete="CASCADE")
    )

    # Relationships
    questions: Mapped[list["Questions"]] = relationship(order_by="Questions.created_at")
    assistant: Mapped[Optional[Assistants]] = relationship(
        foreign_keys="Sessions.assistant_id", viewonly=True
    )

    __table_args__ = (
        Index("ix_sessions_created_id", "created_at", "id"),
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (service_principal_id IS NOT NULL)::int"
            " + (widget_id IS NOT NULL)::int = 1",
            name="ck_sessions_single_principal",
        ),
        CheckConstraint(
            "api_key_id IS NULL OR service_principal_id IS NOT NULL",
            name="ck_sessions_api_key_requires_service_principal",
        ),
        Index(
            "ix_sessions_service_principal_id",
            "service_principal_id",
            postgresql_where=text("service_principal_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(visitor_id IS NULL) = (widget_id IS NULL)",
            name="ck_sessions_visitor_requires_widget",
        ),
        Index(
            "ix_sessions_widget_visitor_created",
            "widget_id",
            "visitor_id",
            sa.text("created_at DESC"),
        ),
    )
