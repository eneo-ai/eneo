from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic

if TYPE_CHECKING:
    from intric.database.tables.integration_table import UserIntegration


class SharePointSubscription(BasePublic):
    """Site-level SharePoint webhook subscriptions shared across integrations.

    One subscription per (user_integration, site) combination, shared by all
    integration_knowledge records on that site for that user.

    This reduces duplicate webhooks and simplifies subscription management.
    """

    __tablename__ = "sharepoint_subscriptions"

    # Composite key: one subscription per user+site
    user_integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_integrations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        Text,
        index=True,
        nullable=False,
        comment="SharePoint site ID (e.g., 'example.sharepoint.com,site-guid,web-guid')"
    )

    # Microsoft Graph subscription details
    subscription_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        comment="Microsoft Graph subscription ID returned from API"
    )
    drive_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Drive ID that this subscription monitors"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When this subscription expires (Microsoft Graph enforces 24h max)"
    )

    # Relationships
    user_integration: Mapped["UserIntegration"] = relationship()

    # Ensure only one subscription per (user_integration, site)
    __table_args__ = (
        UniqueConstraint(
            'user_integration_id',
            'site_id',
            name='uq_sharepoint_subscription_user_site'
        ),
    )
