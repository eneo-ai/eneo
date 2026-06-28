from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from eneo.base.base_entity import Entity


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
        consecutive_renewal_failures: int = 0,
        last_renewal_failed_at: datetime | None = None,
        last_renewal_error: str | None = None,
        last_webhook_received_at: datetime | None = None,
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
        self.consecutive_renewal_failures = consecutive_renewal_failures
        self.last_renewal_failed_at = last_renewal_failed_at
        self.last_renewal_error = last_renewal_error
        self.last_webhook_received_at = last_webhook_received_at

    def mark_renewal_success(self) -> None:
        """Clear renewal failure state after Graph accepts renewal/recreation."""
        self.consecutive_renewal_failures = 0
        self.last_renewal_failed_at = None
        self.last_renewal_error = None

    def mark_renewal_failure(
        self, error_message: str, failed_at: datetime | None = None
    ) -> None:
        """Record a failed renewal attempt for subscription health monitoring."""
        self.consecutive_renewal_failures += 1
        self.last_renewal_failed_at = failed_at or datetime.now(timezone.utc)
        self.last_renewal_error = error_message

    def mark_webhook_received(self, received_at: datetime | None = None) -> None:
        """Record a valid webhook arrival for subscription health monitoring."""
        self.last_webhook_received_at = received_at or datetime.now(timezone.utc)

    def is_expiring_soon(self, hours: int = 4) -> bool:
        """Check if subscription will expire within the specified hours."""
        from datetime import timedelta

        threshold = datetime.now(timezone.utc) + timedelta(hours=hours)
        return self.expires_at <= threshold

    def is_expired(self) -> bool:
        """Check if subscription has already expired."""
        return self.expires_at <= datetime.now(timezone.utc)
