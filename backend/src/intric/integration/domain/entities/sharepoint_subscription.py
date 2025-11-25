from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.base.base_entity import Entity


class SharePointSubscription(Entity):
    """Site-level SharePoint webhook subscription shared across integrations.

    One subscription per (user_integration_id, site_id) combination.
    Multiple integration_knowledge records can reference the same subscription.

    This reduces duplicate webhooks from Microsoft Graph and simplifies
    subscription lifecycle management (renewal, deletion).
    """

    def __init__(
        self,
        user_integration_id: UUID,
        site_id: str,
        subscription_id: str,
        drive_id: str,
        expires_at: datetime,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.user_integration_id = user_integration_id
        self.site_id = site_id
        self.subscription_id = subscription_id
        self.drive_id = drive_id
        self.expires_at = expires_at

    def is_expiring_soon(self, hours: int = 4) -> bool:
        """Check if subscription will expire within the specified hours."""
        from datetime import timedelta, timezone
        threshold = datetime.now(timezone.utc) + timedelta(hours=hours)
        return self.expires_at <= threshold

    def is_expired(self) -> bool:
        """Check if subscription has already expired."""
        from datetime import timezone
        return self.expires_at <= datetime.now(timezone.utc)
