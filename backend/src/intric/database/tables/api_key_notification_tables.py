from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic


class ApiKeyNotificationPreference(BasePublic):
    __tablename__ = "api_key_notification_preferences"  # type: ignore[assignment]

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    days_before_expiry: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )
    auto_follow_published_assistants: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    auto_follow_published_apps: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    __table_args__ = (
        CheckConstraint(
            "days_before_expiry > 0",
            name="ck_api_key_notification_preferences_days_positive",
        ),
    )


class ApiKeyNotificationSubscriptionTable(BasePublic):
    __tablename__ = "api_key_notification_subscriptions"  # type: ignore[assignment]

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="manual",
        server_default="manual",
    )

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('key', 'assistant', 'app', 'space')",
            name="ck_api_key_notification_subscriptions_target_type",
        ),
        CheckConstraint(
            "source IN ('manual', 'auto_follow')",
            name="ck_api_key_notification_subscriptions_source",
        ),
        UniqueConstraint(
            "user_id",
            "target_type",
            "target_id",
            name="uq_api_key_notification_subscription_user_target",
        ),
    )
