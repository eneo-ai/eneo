from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import aiohttp

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionExists,
    SharePointSubscriptionRepository,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointTokenProtocol,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

logger = get_logger(__name__)

RECREATE_FAILED_MESSAGE = (
    "Microsoft Graph did not accept a replacement subscription; "
    "the existing one was kept"
)


def normalize_notification_url(url: str) -> str:
    """The form two spellings of one webhook URL share.

    Scheme and host are case-insensitive and a trailing slash does not change
    which route Eneo serves, so neither may count as drift; path case and the
    query string do.
    """
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


def lifecycle_notification_url_for(
    notification_url: Optional[str], configured: Optional[str]
) -> Optional[str]:
    """Where Graph posts lifecycle events: the configured URL, else the
    notification URL itself. None without a notification URL.

    Graph validates this URL when it creates a subscription. The notification
    URL is already known to reach Eneo, so defaulting to it cannot break
    subscriptions behind a proxy that forwards only that path; the webhook
    tells lifecycle events from changes by their ``lifecycleEvent`` field.
    """
    if not notification_url:
        return None
    if configured and configured.strip():
        return configured.strip()
    return notification_url


def _resource_label(site_id: Optional[str], drive_id: Optional[str] = None) -> str:
    """Safe short label for log messages, handles None values."""
    if site_id:
        return f"site {site_id[:30]}"
    if drive_id:
        return f"drive {drive_id[:30]}"
    return "unknown resource"


class SharePointSubscriptionService:
    """Manages site-level SharePoint webhook subscriptions.

    Each subscription is shared across all integrations for a given (user, site) combination.
    This reduces duplicate webhooks and simplifies subscription management.
    """

    def __init__(
        self,
        sharepoint_subscription_repo: SharePointSubscriptionRepository,
    ) -> None:
        super().__init__()
        self.subscription_repo = sharepoint_subscription_repo
        settings = get_settings()
        self.notification_url = settings.sharepoint_webhook_notification_url
        if not self.notification_url and settings.public_origin:
            self.notification_url = (
                f"{settings.public_origin}/api/v1/integrations/sharepoint/webhook/"
            )
        self.lifecycle_notification_url = lifecycle_notification_url_for(
            self.notification_url,
            settings.sharepoint_webhook_lifecycle_notification_url,
        )
        self.client_state = (
            settings.sharepoint_webhook_client_state.strip()
            if settings.sharepoint_webhook_client_state
            else None
        )
        # Microsoft Graph allows up to 42,300 minutes (29.375 days) for driveItem subscriptions
        # We use 42,000 minutes (~29 days) to stay safely under the limit
        self.subscription_lifetime_minutes = 42000

    def _require_client_state(self) -> str:
        if not self.client_state:
            raise ValueError(
                "SHAREPOINT_WEBHOOK_CLIENT_STATE must be configured "
                "before creating SharePoint webhook subscriptions."
            )
        return self.client_state

    def require_webhook_configuration(self) -> None:
        """Raise ``ValueError`` naming what a Graph subscription cannot be created without."""
        if not self.notification_url:
            raise ValueError(
                "Set PUBLIC_ORIGIN or SHAREPOINT_WEBHOOK_NOTIFICATION_URL "
                "before creating SharePoint webhook subscriptions."
            )
        self._require_client_state()

    def notification_url_drifted(self, subscription: SharePointSubscription) -> bool:
        """True when Graph still posts to a URL this deployment no longer serves."""
        return bool(
            self.notification_url
            and subscription.notification_url is not None
            and normalize_notification_url(subscription.notification_url)
            != normalize_notification_url(self.notification_url)
        )

    def lifecycle_url_missing(self, subscription: SharePointSubscription) -> bool:
        """True when Graph does not post this subscription's lifecycle events here.

        Graph takes ``lifecycleNotificationUrl`` only when a subscription is
        created, so such a subscription is recreated rather than renewed.
        """
        if not self.lifecycle_notification_url:
            return False
        stored = subscription.lifecycle_notification_url
        return stored is None or normalize_notification_url(
            stored
        ) != normalize_notification_url(self.lifecycle_notification_url)

    async def ensure_subscription_for_site(
        self,
        user_integration_id: UUID,
        site_id: str,
        token: SharePointTokenProtocol,
        is_onedrive: bool = False,
    ) -> Optional[SharePointSubscription]:
        """Ensure a subscription exists for this user+site/drive combination.

        If a subscription already exists, returns it without creating a new one.
        If no subscription exists, creates one and returns it.

        This is the main entry point for integration creation - replaces the old
        per-integration subscription logic.

        The subscription row is written in a transaction of its own, committed
        before this returns, so Graph and the row agree whatever becomes of
        the caller's transaction. The caller must hold no lock on the row.

        Args:
            user_integration_id: User integration that owns this subscription
            site_id: SharePoint site ID, or OneDrive drive_id if is_onedrive=True
            token: OAuth token for Microsoft Graph API
            is_onedrive: If True, site_id is actually a drive_id for OneDrive

        Returns:
            SharePointSubscription if successful, None if subscription creation failed
        """
        if not self.notification_url:
            logger.warning(
                "SharePoint webhook notification URL not configured; skipping subscription. "
                "Set PUBLIC_ORIGIN or SHAREPOINT_WEBHOOK_NOTIFICATION_URL in environment."
            )
            return None

        # Imports and syncs of several folders on one site arrive together
        # ("Resync all" sends a few at once). Each would find the same missing,
        # expired or drifted subscription and create one at Graph, and all but
        # the last written would be left there unused. The pair is therefore
        # locked, in a transaction of its own that ends here: held until the
        # caller's transaction ended, it would also wait on whatever that
        # transaction waits for (a running sync's row), and a batch over two
        # sites could deadlock with another taking them in the other order.
        async with self.subscription_repo.own_transaction() as repo:
            return await self._ensure(
                repo, user_integration_id, site_id, token, is_onedrive
            )

    async def _ensure(
        self,
        repo: SharePointSubscriptionRepository,
        user_integration_id: UUID,
        site_id: str,
        token: SharePointTokenProtocol,
        is_onedrive: bool,
    ) -> Optional[SharePointSubscription]:
        existing = await repo.lock_user_site(
            user_integration_id=user_integration_id, site_id=site_id
        )

        if existing:
            # Check if subscription is expired (happens during local development
            # or server downtime > 24h)
            if existing.is_expired():
                logger.warning(
                    f"Subscription {existing.subscription_id} for {_resource_label(site_id)} has expired. "
                    f"Attempting automatic recreation to preserve integration relationships."
                )
                success = await self.recreate_expired_subscription(
                    subscription=existing,
                    token=token,
                    is_onedrive=is_onedrive,
                    repo=repo,
                )
                if success:
                    logger.info(
                        f"Successfully recreated expired subscription for {_resource_label(site_id)}"
                    )
                    return existing  # Same DB object, updated with new subscription_id
                else:
                    logger.error(
                        f"Failed to recreate expired subscription for {_resource_label(site_id)}, "
                        f"returning expired subscription (webhooks will not work until recreated)"
                    )
                    return existing  # Return expired subscription - better than None
            if self.notification_url_drifted(existing):
                logger.warning(
                    f"Subscription {existing.subscription_id} for {_resource_label(site_id)} "
                    f"posts to {existing.notification_url}; recreating for {self.notification_url}"
                )
                await self.recreate_expired_subscription(
                    subscription=existing,
                    token=token,
                    is_onedrive=is_onedrive,
                    repo=repo,
                )
                return existing
            logger.info(
                f"Reusing existing subscription {existing.subscription_id} "
                f"for user_integration={user_integration_id}, {_resource_label(site_id)}"
            )
            return existing

        # Create new subscription
        resource_type = "OneDrive" if is_onedrive else "site"
        logger.info(
            f"Creating new {resource_type}-level subscription for user_integration={user_integration_id}, "
            f"{_resource_label(site_id)}"
        )

        if is_onedrive:
            # For OneDrive, site_id IS the drive_id
            drive_id = site_id
        else:
            # For SharePoint sites, resolve drive_id from site
            drive_id = await self._resolve_drive_id(token=token, site_id=site_id)
            if not drive_id:
                logger.warning(
                    f"Could not resolve drive_id for {_resource_label(site_id)}; cannot create subscription"
                )
                return None

        subscription_id = await self._create_graph_subscription(
            token=token,
            site_id=site_id if not is_onedrive else None,
            drive_id=drive_id,
        )

        if not subscription_id:
            logger.warning(
                f"Failed to create Microsoft Graph subscription for {_resource_label(site_id, drive_id)}"
            )
            return None

        # Save to database
        expiration = datetime.now(timezone.utc) + timedelta(
            minutes=self.subscription_lifetime_minutes
        )
        subscription = SharePointSubscription(
            user_integration_id=user_integration_id,
            site_id=site_id,
            subscription_id=subscription_id,
            drive_id=drive_id,
            expires_at=expiration,
            notification_url=self.notification_url,
            lifecycle_notification_url=self.lifecycle_notification_url,
        )

        try:
            saved = await repo.add(subscription)
        except SharePointSubscriptionExists:
            # Lost the race with a concurrent import of the same site: keep the
            # row that won and drop the Graph subscription we just registered,
            # or Graph would post every change twice.
            winner = await repo.get_by_user_and_site(
                user_integration_id=user_integration_id, site_id=site_id
            )
            logger.info(
                f"Subscription for {_resource_label(site_id)} was created concurrently; "
                f"deleting duplicate Graph subscription {subscription_id}"
            )
            await self._delete_graph_subscription(
                subscription_id=subscription_id, token=token
            )
            return winner
        logger.info(
            f"Created and saved subscription {subscription_id} for {_resource_label(site_id, drive_id)} "
            f"(expires {expiration.isoformat()})"
        )

        return saved

    async def recreate_expired_subscription(
        self,
        subscription: SharePointSubscription,
        token: SharePointTokenProtocol,
        is_onedrive: bool = False,
        repo: Optional[SharePointSubscriptionRepository] = None,
    ) -> bool:
        """Recreate an expired subscription in-place.

        When a subscription has expired (server downtime > 24h), Microsoft Graph
        won't allow renewal via PATCH. This method creates a new subscription
        and updates the existing DB record with the new subscription_id and expires_at.

        This preserves all FK relationships to integration_knowledge, so all
        assistants using this SharePoint integration continue to work.

        Args:
            subscription: Expired subscription to recreate
            token: OAuth token for Microsoft Graph API
            is_onedrive: If True, this is an OneDrive subscription (no site_id in Graph API)

        Returns:
            True if recreation successful, False otherwise
        """
        self.require_webhook_configuration()
        repo = repo or self.subscription_repo
        logger.info(
            f"Recreating expired subscription {subscription.subscription_id} "
            f"for {_resource_label(subscription.site_id, subscription.drive_id)}"
        )
        old_subscription_id = subscription.subscription_id

        # Graph allows two subscriptions on one resource, so the replacement is
        # created while the old one still stands. A failed create (the new
        # origin not yet serving TLS, Graph refusing the validation handshake)
        # then leaves Graph and the row as they were; a row left with a deleted
        # id would not be looked at again until its stored expiry.
        new_subscription_id = await self._create_graph_subscription(
            token=token,
            site_id=subscription.site_id if not is_onedrive else None,
            drive_id=subscription.drive_id,
        )

        if not new_subscription_id:
            logger.error(
                f"Failed to create a replacement for subscription {subscription.id}; "
                f"keeping {old_subscription_id[:20]}..."
            )
            subscription.mark_renewal_failure(
                user_visible_error(RECREATE_FAILED_MESSAGE)
            )
            try:
                await repo.update(subscription)
            except Exception as exc:
                logger.warning(
                    "Could not record the failed recreation of subscription %s (%s)",
                    subscription.id,
                    type(exc).__name__,
                )
            return False

        new_expiration = datetime.now(timezone.utc) + timedelta(
            minutes=self.subscription_lifetime_minutes
        )
        subscription.subscription_id = new_subscription_id
        subscription.expires_at = new_expiration
        subscription.notification_url = self.notification_url
        subscription.lifecycle_notification_url = self.lifecycle_notification_url
        subscription.mark_renewal_success()
        # The row is written before the old subscription is deleted: a failed
        # write must not leave the row pointing at a subscription Graph no
        # longer has. The old one may already be gone; a delete that fails
        # leaves an orphan that expires at Graph on its own.
        await repo.update(subscription)
        if not await self._delete_graph_subscription(
            subscription_id=old_subscription_id, token=token
        ):
            logger.warning(
                "Replaced subscription %s but could not delete the old Graph "
                "subscription %s; it expires at Graph on its own",
                subscription.id,
                old_subscription_id[:20],
            )

        logger.info(
            f"Successfully recreated subscription {subscription.id}: "
            f"old_id={old_subscription_id[:20]}..., "
            f"new_id={new_subscription_id[:20]}..., "
            f"expires={new_expiration.isoformat()}"
        )

        return True

    async def renew_subscription(
        self,
        subscription: SharePointSubscription,
        token: SharePointTokenProtocol,
    ) -> bool:
        """Renew an existing subscription before it expires.

        Called by background renewal job to extend subscription lifetime.

        Args:
            subscription: Subscription to renew
            token: OAuth token for Microsoft Graph API

        Returns:
            True if renewal successful, False otherwise
        """
        if self.notification_url_drifted(subscription):
            # Graph cannot be told a new notificationUrl on renewal; only a
            # fresh subscription carries it.
            logger.warning(
                f"Subscription {subscription.subscription_id} posts to "
                f"{subscription.notification_url}; recreating for {self.notification_url}"
            )
            return await self.recreate_expired_subscription(
                subscription=subscription,
                token=token,
                is_onedrive=subscription.is_onedrive,
            )
        if self.lifecycle_url_missing(subscription):
            logger.info(
                f"Subscription {subscription.subscription_id} has no lifecycle "
                f"notification URL; recreating it for {self.lifecycle_notification_url}"
            )
            if await self.recreate_expired_subscription(
                subscription=subscription,
                token=token,
                is_onedrive=subscription.is_onedrive,
            ):
                return True
            # Renewed in place it keeps working, only without lifecycle events.
            logger.warning(
                f"Could not recreate subscription {subscription.subscription_id} "
                "with a lifecycle notification URL; renewing it as it is"
            )

        new_expiration = datetime.now(timezone.utc) + timedelta(
            minutes=self.subscription_lifetime_minutes
        )

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

            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                async with session.patch(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{subscription.subscription_id}",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status == 200:
                        # Update database
                        subscription.expires_at = new_expiration
                        subscription.mark_renewal_success()
                        await self.subscription_repo.update(subscription)

                        logger.info(
                            f"Renewed subscription {subscription.subscription_id} "
                            f"for {_resource_label(subscription.site_id, subscription.drive_id)} until {new_expiration.isoformat()}"
                        )
                        return True
                    elif response.status == 404:
                        # Subscription not found in Microsoft Graph - likely due to DB rollback
                        # or Microsoft deleted it. Automatically recreate to recover.
                        logger.warning(
                            f"Subscription {subscription.subscription_id} not found in Microsoft Graph "
                            f"(404 response). Automatically recreating to recover from potential DB rollback "
                            f"or sync issue for {_resource_label(subscription.site_id, subscription.drive_id)}"
                        )
                        # Recreate subscription in-place (preserves all FK relationships)
                        return await self.recreate_expired_subscription(
                            subscription=subscription,
                            token=token,
                            is_onedrive=subscription.is_onedrive,
                        )
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
                exc_info=True,
            )
            return False

    async def delete_subscription_if_unused(
        self,
        subscription_id: UUID,
        token: SharePointTokenProtocol,
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
        subscription = await self.subscription_repo.one_or_none(id=subscription_id)
        if not subscription:
            logger.warning(f"Subscription {subscription_id} not found in database")
            return True  # Already deleted

        # Delete from Microsoft Graph
        deleted = await self._delete_graph_subscription(
            subscription_id=subscription.subscription_id, token=token
        )

        if deleted:
            # Delete from database
            await self.subscription_repo.delete(id=subscription_id)
            logger.info(
                f"Deleted subscription {subscription.subscription_id} "
                f"for {_resource_label(subscription.site_id, subscription.drive_id)} (no more references)"
            )
            return True
        else:
            logger.warning(
                f"Failed to delete subscription {subscription.subscription_id} from Microsoft Graph; "
                f"keeping in database for retry"
            )
            return False

    async def list_expiring_subscriptions(
        self, hours: int = 4
    ) -> list[SharePointSubscription]:
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
        token: SharePointTokenProtocol,
        site_id: Optional[str],
        drive_id: str,
    ) -> Optional[str]:
        """Create subscription in Microsoft Graph.

        Args:
            token: OAuth token for Microsoft Graph API
            site_id: SharePoint site ID (None for OneDrive)
            drive_id: Drive ID

        Returns:
            subscription_id from Microsoft Graph, or None on failure.
        """
        expiration = datetime.now(timezone.utc) + timedelta(
            minutes=self.subscription_lifetime_minutes
        )

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
        }

        # Microsoft Graph subscriptions only support drive/root level resources
        # We always subscribe to the entire drive root
        # Webhook handler filters notifications based on folder_id in IntegrationKnowledge
        if site_id:
            # SharePoint: use full site/drive path
            resource = f"/sites/{site_id}/drives/{drive_id}/root"
        else:
            # OneDrive: use just the drive path
            resource = f"/drives/{drive_id}/root"

        payload = {
            "changeType": "updated",  # Covers create/delete/update events
            "notificationUrl": self.notification_url,
            "resource": resource,
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
            "clientState": self._require_client_state(),
        }
        if self.lifecycle_notification_url:
            # Graph validates this URL like the notification URL, and only
            # accepts it here: a renewal cannot add it later.
            payload["lifecycleNotificationUrl"] = self.lifecycle_notification_url

        try:
            # Use IPv4-only connector to avoid IPv6 issues
            connector = aiohttp.TCPConnector(family=socket.AF_INET, force_close=True)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                async with session.post(
                    "https://graph.microsoft.com/v1.0/subscriptions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status == 201:
                        data = await response.json()
                        subscription_id = data.get("id")
                        resource_kind = "drive" if not site_id else "site"
                        resource_id = drive_id if not site_id else site_id
                        logger.info(
                            f"Created Microsoft Graph subscription {subscription_id} "
                            f"for {resource_kind} {resource_id[:30]}..., drive {drive_id[:20]}..."
                        )
                        return subscription_id
                    else:
                        error_text = await response.text()
                        resource_kind = "drive" if not site_id else "site"
                        resource_id = drive_id if not site_id else site_id
                        logger.error(
                            f"Failed to create subscription for {resource_kind} {resource_id}: "
                            f"HTTP {response.status} - {error_text}"
                        )
                        return None

        except Exception as exc:
            resource_kind = "drive" if not site_id else "site"
            resource_id = drive_id if not site_id else site_id
            logger.error(
                f"Error creating subscription for {resource_kind} {resource_id}: {exc}",
                exc_info=True,
            )
            return None

    async def _delete_graph_subscription(
        self,
        subscription_id: str,
        token: SharePointTokenProtocol,
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

            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                async with session.delete(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{subscription_id}",
                    headers=headers,
                ) as response:
                    if response.status == 204:
                        logger.info(
                            f"Deleted Microsoft Graph subscription {subscription_id}"
                        )
                        return True
                    elif response.status == 404:
                        # Already deleted - that's fine
                        logger.info(
                            f"Subscription {subscription_id} already deleted from Microsoft Graph"
                        )
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
                f"Error deleting subscription {subscription_id}: {exc}", exc_info=True
            )
            return False

    async def delete_subscription_if_unused_detached(
        self,
        subscription_id: UUID,
        token: SharePointTokenProtocol,
    ) -> None:
        """``delete_subscription_if_unused`` on a session of its own.

        For work scheduled past the end of a request, whose session is closed
        by the time this runs.
        """
        from eneo.database.database import sessionmanager
        from eneo.integration.infrastructure.mappers.sharepoint_subscription_mapper import (
            SharePointSubscriptionMapper,
        )
        from eneo.integration.infrastructure.sharepoint_subscription_repo_impl import (
            SharePointSubscriptionRepositoryImpl,
        )

        async with sessionmanager.session() as session, session.begin():
            detached = SharePointSubscriptionService(
                sharepoint_subscription_repo=SharePointSubscriptionRepositoryImpl(
                    session=session, mapper=SharePointSubscriptionMapper()
                ),
            )
            await detached.delete_subscription_if_unused(
                subscription_id=subscription_id, token=token
            )

    async def _resolve_drive_id(
        self,
        token: SharePointTokenProtocol,
        site_id: str,
    ) -> Optional[str]:
        """Resolve drive ID for a SharePoint site.

        Uses SharePointContentClient to get default drive ID.
        """
        try:
            base_url = token.base_url
            async with SharePointContentClient(
                base_url=base_url,
                api_token=token.access_token,
            ) as content_client:
                drive_id = await content_client.get_default_drive_id(site_id=site_id)
                return drive_id
        except Exception as exc:
            logger.error(
                f"Error resolving drive ID for site {site_id}: {exc}", exc_info=True
            )
            return None
