from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from eneo.integration.domain.entities.sharepoint_subscription import (
        SharePointSubscription,
    )


class SharePointSubscriptionExists(Exception):
    """A subscription for this (user integration, site) was stored concurrently."""

    def __init__(self, user_integration_id: UUID, site_id: str) -> None:
        super().__init__(
            f"Subscription already exists for user integration {user_integration_id} "
            f"and site {site_id}"
        )
        self.user_integration_id = user_integration_id
        self.site_id = site_id


class SharePointSubscriptionRepository(ABC):
    """Repository for managing SharePoint webhook subscriptions."""

    @abstractmethod
    async def one_or_none(
        self,
        id: UUID | None = None,
        **filters: object,
    ) -> "Optional[SharePointSubscription]":
        """Get a single subscription by ID or filters, returning None if not found."""
        ...

    @abstractmethod
    async def add(self, obj: "SharePointSubscription") -> "SharePointSubscription":
        """Persist and return a new subscription."""
        ...

    @abstractmethod
    async def update(self, obj: "SharePointSubscription") -> "SharePointSubscription":
        """Persist and return an updated subscription."""
        ...

    @abstractmethod
    async def delete(self, id: UUID) -> bool:
        """Delete a subscription by database ID."""
        ...

    @abstractmethod
    async def get_by_user_and_site(
        self, user_integration_id: UUID, site_id: str
    ) -> "Optional[SharePointSubscription]":
        """Get subscription for a specific user+site combination.

        Returns None if no subscription exists for this combination.
        """
        ...

    @abstractmethod
    async def lock_user_site(
        self, user_integration_id: UUID, site_id: str
    ) -> "Optional[SharePointSubscription]":
        """Serialize work on one user+site subscription for the transaction.

        Waits until no other transaction holds the same user+site, holds it
        until this transaction ends, and returns the subscription as committed
        by the previous holder (None if there is none yet).
        """
        ...

    @abstractmethod
    async def get_by_subscription_id(
        self, subscription_id: str
    ) -> "Optional[SharePointSubscription]":
        """Get subscription by Microsoft Graph subscription ID."""
        ...

    @abstractmethod
    async def list_expiring_before(
        self, expires_before: datetime
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
    async def list_by_tenant(self, tenant_id: UUID) -> "List[SharePointSubscription]":
        """List all subscriptions that belong to a tenant."""
        ...

    @abstractmethod
    async def one_by_tenant(
        self,
        subscription_id: UUID,
        tenant_id: UUID,
    ) -> "Optional[SharePointSubscription]":
        """Get a subscription by ID, scoped to tenant."""
        ...

    @abstractmethod
    async def count_references(self, subscription_id: UUID) -> int:
        """Count how many integration_knowledge records reference this subscription.

        Used to determine if subscription can be safely deleted (0 references).
        """
        ...

    @abstractmethod
    async def link_unreferenced_knowledge(
        self, subscription: "SharePointSubscription"
    ) -> int:
        """Point knowledge rows for the subscription's resource at it.

        Rows of the same user integration and site (or OneDrive drive) whose
        link is still NULL get it; returns how many rows were linked. A row
        another transaction holds (a running sync) is skipped, not waited
        for; that sync links it itself.
        """
        ...

    @abstractmethod
    def own_transaction(
        self,
    ) -> "AbstractAsyncContextManager[SharePointSubscriptionRepository]":
        """A repository on a session and transaction of its own, committed when
        the block ends."""
        ...
