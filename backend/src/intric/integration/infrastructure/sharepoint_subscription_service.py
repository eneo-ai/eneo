from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import UUID

import aiohttp
import socket

from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionRepository,
)
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from intric.integration.infrastructure.oauth_token_service import OauthTokenService
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


class SharePointSubscriptionService:
    """Manages site-level SharePoint webhook subscriptions.

    Each subscription is shared across all integrations for a given (user, site) combination.
    This reduces duplicate webhooks and simplifies subscription management.
    """

    def __init__(
        self,
        sharepoint_subscription_repo: SharePointSubscriptionRepository,
        oauth_token_service: OauthTokenService,
    ):
        self.subscription_repo = sharepoint_subscription_repo
        self.oauth_token_service = oauth_token_service
        settings = get_settings()
        self.notification_url = settings.sharepoint_webhook_notification_url
        self.client_state = settings.sharepoint_webhook_client_state
        self.subscription_lifetime_minutes = settings.sharepoint_subscription_lifetime_minutes or 1440

    async def ensure_subscription_for_site(
        self,
        user_integration_id: UUID,
        site_id: str,
        token: SharePointToken,
    ) -> Optional[SharePointSubscription]:
        """Ensure a subscription exists for this user+site combination.

        If a subscription already exists, returns it without creating a new one.
        If no subscription exists, creates one and returns it.

        This is the main entry point for integration creation - replaces the old
        per-integration subscription logic.

        Args:
            user_integration_id: User integration that owns this subscription
            site_id: SharePoint site ID
            token: OAuth token for Microsoft Graph API

        Returns:
            SharePointSubscription if successful, None if subscription creation failed
        """
        if not self.notification_url:
            logger.debug("SharePoint webhook notification URL not configured; skipping subscription")
            return None

        # Check if subscription already exists for this user+site
        existing = await self.subscription_repo.get_by_user_and_site(
            user_integration_id=user_integration_id,
            site_id=site_id
        )

        if existing:
            logger.info(
                f"Reusing existing subscription {existing.subscription_id} "
                f"for user_integration={user_integration_id}, site={site_id[:30]}..."
            )
            return existing

        # Create new subscription
        logger.info(
            f"Creating new site-level subscription for user_integration={user_integration_id}, "
            f"site={site_id[:30]}..."
        )

        drive_id = await self._resolve_drive_id(token=token, site_id=site_id)
        if not drive_id:
            logger.warning(f"Could not resolve drive_id for site {site_id}; cannot create subscription")
            return None

        subscription_id = await self._create_graph_subscription(
            token=token,
            site_id=site_id,
            drive_id=drive_id
        )

        if not subscription_id:
            logger.warning(f"Failed to create Microsoft Graph subscription for site {site_id}")
            return None

        # Save to database
        expiration = datetime.now(timezone.utc) + timedelta(minutes=self.subscription_lifetime_minutes)
        subscription = SharePointSubscription(
            user_integration_id=user_integration_id,
            site_id=site_id,
            subscription_id=subscription_id,
            drive_id=drive_id,
            expires_at=expiration,
        )

        saved = await self.subscription_repo.add(subscription)
        logger.info(
            f"Created and saved subscription {subscription_id} for site {site_id[:30]}... "
            f"(expires {expiration.isoformat()})"
        )

        return saved

    async def renew_subscription(
        self,
        subscription: SharePointSubscription,
        token: SharePointToken,
    ) -> bool:
        """Renew an existing subscription before it expires.

        Called by background renewal job to extend subscription lifetime.

        Args:
            subscription: Subscription to renew
            token: OAuth token for Microsoft Graph API

        Returns:
            True if renewal successful, False otherwise
        """
        new_expiration = datetime.now(timezone.utc) + timedelta(minutes=self.subscription_lifetime_minutes)

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "expirationDateTime": new_expiration.isoformat().replace("+00:00", "Z"),
        }

        try:
            # Use IPv4-only connector to avoid IPv6 issues
            connector = aiohttp.TCPConnector(family=socket.AF_INET, force_close=True)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.patch(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{subscription.subscription_id}",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status == 200:
                        # Update database
                        subscription.expires_at = new_expiration
                        await self.subscription_repo.update(subscription)

                        logger.info(
                            f"Renewed subscription {subscription.subscription_id} "
                            f"for site {subscription.site_id[:30]}... until {new_expiration.isoformat()}"
                        )
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to renew subscription {subscription.subscription_id}: "
                            f"HTTP {response.status} - {error_text}"
                        )
                        return False

        except Exception as exc:
            logger.error(
                f"Error renewing subscription {subscription.subscription_id}: {exc}",
                exc_info=True
            )
            return False

    async def delete_subscription_if_unused(
        self,
        subscription_id: UUID,
        token: SharePointToken,
    ) -> bool:
        """Delete subscription if no integration_knowledge records reference it.

        Called when an integration is deleted. Only deletes if this was the last
        integration using this subscription.

        Args:
            subscription_id: Subscription database ID
            token: OAuth token for Microsoft Graph API

        Returns:
            True if deleted (or didn't need deletion), False on error
        """
        # Check if any integrations still reference this subscription
        ref_count = await self.subscription_repo.count_references(subscription_id)

        if ref_count > 0:
            logger.info(
                f"Subscription {subscription_id} still has {ref_count} references; "
                f"not deleting"
            )
            return True

        # No references - safe to delete
        subscription = await self.subscription_repo.get(subscription_id)
        if not subscription:
            logger.warning(f"Subscription {subscription_id} not found in database")
            return True  # Already deleted

        # Delete from Microsoft Graph
        deleted = await self._delete_graph_subscription(
            subscription_id=subscription.subscription_id,
            token=token
        )

        if deleted:
            # Delete from database
            await self.subscription_repo.remove(id=subscription_id)
            logger.info(
                f"Deleted subscription {subscription.subscription_id} "
                f"for site {subscription.site_id[:30]}... (no more references)"
            )
            return True
        else:
            logger.warning(
                f"Failed to delete subscription {subscription.subscription_id} from Microsoft Graph; "
                f"keeping in database for retry"
            )
            return False

    async def list_expiring_subscriptions(
        self,
        hours: int = 4
    ) -> List[SharePointSubscription]:
        """List subscriptions expiring within the specified hours.

        Used by renewal background job.

        Args:
            hours: Look ahead this many hours

        Returns:
            List of subscriptions that need renewal
        """
        threshold = datetime.now(timezone.utc) + timedelta(hours=hours)
        return await self.subscription_repo.list_expiring_before(threshold)

    async def _create_graph_subscription(
        self,
        token: SharePointToken,
        site_id: str,
        drive_id: str,
    ) -> Optional[str]:
        """Create subscription in Microsoft Graph.

        Returns subscription_id from Microsoft Graph, or None on failure.
        """
        expiration = datetime.now(timezone.utc) + timedelta(minutes=self.subscription_lifetime_minutes)

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
        }

        # Microsoft Graph subscriptions only support drive/root level resources
        # We always subscribe to the entire drive root
        # Webhook handler filters notifications based on folder_id in IntegrationKnowledge
        resource = f"/sites/{site_id}/drives/{drive_id}/root"

        payload = {
            "changeType": "updated",  # Covers create/delete/update events
            "notificationUrl": self.notification_url,
            "resource": resource,
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
        }

        if self.client_state:
            payload["clientState"] = self.client_state

        try:
            # Use IPv4-only connector to avoid IPv6 issues
            connector = aiohttp.TCPConnector(family=socket.AF_INET, force_close=True)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(
                    "https://graph.microsoft.com/v1.0/subscriptions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status == 201:
                        data = await response.json()
                        subscription_id = data.get("id")
                        logger.info(
                            f"Created Microsoft Graph subscription {subscription_id} "
                            f"for site {site_id[:30]}..., drive {drive_id[:20]}..."
                        )
                        return subscription_id
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to create subscription for site {site_id}: "
                            f"HTTP {response.status} - {error_text}"
                        )
                        return None

        except Exception as exc:
            logger.error(
                f"Error creating subscription for site {site_id}: {exc}",
                exc_info=True
            )
            return None

    async def _delete_graph_subscription(
        self,
        subscription_id: str,
        token: SharePointToken,
    ) -> bool:
        """Delete subscription from Microsoft Graph.

        Returns True if successful or already deleted, False on error.
        """
        headers = {
            "Authorization": f"Bearer {token.access_token}",
        }

        try:
            connector = aiohttp.TCPConnector(family=socket.AF_INET, force_close=True)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.delete(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{subscription_id}",
                    headers=headers,
                ) as response:
                    if response.status == 204:
                        logger.info(f"Deleted Microsoft Graph subscription {subscription_id}")
                        return True
                    elif response.status == 404:
                        # Already deleted - that's fine
                        logger.info(f"Subscription {subscription_id} already deleted from Microsoft Graph")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to delete subscription {subscription_id}: "
                            f"HTTP {response.status} - {error_text}"
                        )
                        return False

        except Exception as exc:
            logger.error(
                f"Error deleting subscription {subscription_id}: {exc}",
                exc_info=True
            )
            return False

    async def _resolve_drive_id(
        self,
        token: SharePointToken,
        site_id: str,
    ) -> Optional[str]:
        """Resolve drive ID for a SharePoint site.

        Uses SharePointContentClient to get default drive ID.
        """
        try:
            content_client = SharePointContentClient(token=token)
            drive_id = await content_client.get_default_drive_id(site_id=site_id)
            return drive_id
        except Exception as exc:
            logger.error(
                f"Error resolving drive ID for site {site_id}: {exc}",
                exc_info=True
            )
            return None
