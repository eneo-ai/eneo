from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription


class SharePointSubscriptionRepository(ABC):
    """Repository for managing SharePoint webhook subscriptions."""

    @abstractmethod
    async def get_by_user_and_site(
        self,
        user_integration_id: UUID,
        site_id: str
    ) -> "Optional[SharePointSubscription]":
        """Get subscription for a specific user+site combination.

        Returns None if no subscription exists for this combination.
        """
        ...

    @abstractmethod
    async def get_by_subscription_id(
        self,
        subscription_id: str
    ) -> "Optional[SharePointSubscription]":
        """Get subscription by Microsoft Graph subscription ID."""
        ...

    @abstractmethod
    async def list_expiring_before(
        self,
        expires_before: datetime
    ) -> "List[SharePointSubscription]":
        """List all subscriptions expiring before the given datetime.

        Used by renewal background job to find subscriptions that need renewal.
        """
        ...

    @abstractmethod
    async def list_all(self) -> "List[SharePointSubscription]":
        """List all active subscriptions.

        Used for health monitoring and admin endpoints.
        """
        ...

    @abstractmethod
    async def count_references(
        self,
        subscription_id: UUID
    ) -> int:
        """Count how many integration_knowledge records reference this subscription.

        Used to determine if subscription can be safely deleted (0 references).
        """
        ...
