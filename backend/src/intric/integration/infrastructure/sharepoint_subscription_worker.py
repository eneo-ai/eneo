"""ARQ background worker for SharePoint subscription maintenance.

This worker handles:
1. Subscription renewal - runs every 12 hours to renew expiring subscriptions
2. Orphaned subscription cleanup - runs daily to remove unused subscriptions
"""

from typing import Optional

from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription
from intric.integration.infrastructure.content_service.sharepoint_content_service import (
    SimpleSharePointToken,
)
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.worker.worker import Worker

logger = get_logger(__name__)

worker = Worker()


async def get_token_for_subscription(
    subscription: SharePointSubscription,
    container: Container,
) -> Optional[SimpleSharePointToken]:
    """Get SharePoint token for a subscription based on its auth type.

    Handles both user OAuth and tenant app authentication methods.

    Args:
        subscription: The SharePoint subscription
        container: DI container for accessing services

    Returns:
        SharePointToken if successful, None if token cannot be obtained
    """
    user_integration_repo = container.user_integration_repo()
    oauth_token_service = container.oauth_token_service()

    try:
        user_integration = await user_integration_repo.one(id=subscription.user_integration_id)
    except Exception as e:
        logger.error(
            f"Failed to get user integration for subscription {subscription.subscription_id}: {e}"
        )
        return None

    if user_integration.auth_type == "tenant_app":
        # Tenant app auth - get token from tenant app service
        if not user_integration.tenant_app_id:
            logger.warning(
                f"Subscription {subscription.subscription_id} has tenant_app auth but no tenant_app_id"
            )
            return None

        try:
            tenant_sharepoint_app_repo = container.tenant_sharepoint_app_repo()
            tenant_app = await tenant_sharepoint_app_repo.one(id=user_integration.tenant_app_id)

            if tenant_app.is_service_account():
                service_account_auth_service = container.service_account_auth_service()
                token_data = await service_account_auth_service.refresh_access_token(tenant_app)
                new_refresh_token = token_data.get("refresh_token")
                if new_refresh_token and new_refresh_token != tenant_app.service_account_refresh_token:
                    tenant_app.update_refresh_token(new_refresh_token)
                    await tenant_sharepoint_app_repo.update(tenant_app)
                access_token = token_data["access_token"]
            else:
                tenant_app_auth_service = container.tenant_app_auth_service()
                access_token = await tenant_app_auth_service.get_access_token(tenant_app)

            return SimpleSharePointToken(access_token=access_token)

        except Exception as e:
            logger.error(
                f"Failed to get tenant app token for subscription {subscription.subscription_id}: {e}"
            )
            return None
    else:
        # User OAuth auth - get and refresh token
        try:
            token = await oauth_token_service.get_oauth_token_by_user_integration(
                user_integration_id=subscription.user_integration_id
            )

            if not token:
                logger.warning(
                    f"No OAuth token found for subscription {subscription.subscription_id}"
                )
                return None

            if not token.token_type.is_sharepoint:
                logger.warning(
                    f"Token for subscription {subscription.subscription_id} is not a SharePoint token"
                )
                return None

            # Refresh token if needed
            token = await oauth_token_service.refresh_and_update_token(token_id=token.id)
            return token

        except Exception as e:
            logger.error(
                f"Failed to get/refresh OAuth token for subscription {subscription.subscription_id}: {e}"
            )
            return None


@worker.cron_job(minute=0, hour={0, 12})  # Every 12 hours (midnight and noon)
async def renew_expiring_subscriptions(container: Container):
    """Renew SharePoint subscriptions expiring within the next 48 hours.

    Microsoft Graph subscriptions expire after ~29 days max. We renew them
    48 hours (2 days) before expiration to ensure continuous webhook notifications.

    Runs every 12 hours to catch all subscriptions before they expire.

    Supports both user OAuth and tenant app authentication methods.
    """
    logger.info("Starting SharePoint subscription renewal job")

    sharepoint_subscription_service = container.sharepoint_subscription_service()

    # Find subscriptions expiring in next 48 hours (2 days)
    expiring = await sharepoint_subscription_service.list_expiring_subscriptions(hours=48)

    if not expiring:
        logger.info("No subscriptions need renewal")
        return {"renewed": 0, "failed": 0}

    logger.info(f"Found {len(expiring)} subscriptions to renew")

    renewed_count = 0
    failed_count = 0

    for subscription in expiring:
        try:
            # Get token using unified helper (supports both OAuth and tenant app)
            token = await get_token_for_subscription(subscription, container)

            if not token:
                logger.warning(
                    f"Could not get token for subscription {subscription.subscription_id}"
                )
                failed_count += 1
                continue

            # Renew subscription
            success = await sharepoint_subscription_service.renew_subscription(
                subscription=subscription,
                token=token
            )

            if success:
                renewed_count += 1
            else:
                failed_count += 1

        except Exception as exc:
            logger.error(
                f"Error renewing subscription {subscription.subscription_id}: {exc}",
                exc_info=True
            )
            failed_count += 1

    logger.info(
        f"Subscription renewal job complete: {renewed_count} renewed, {failed_count} failed"
    )

    return {"renewed": renewed_count, "failed": failed_count}


@worker.cron_job(hour=2, minute=0)  # Run daily at 2 AM
async def cleanup_orphaned_subscriptions(container: Container):
    """Clean up SharePoint subscriptions with no references.

    When all integration_knowledge records referencing a subscription are deleted,
    the subscription becomes orphaned. This job deletes such subscriptions from
    both Microsoft Graph and our database.

    Runs daily at 2 AM to avoid interfering with active usage.

    Supports both user OAuth and tenant app authentication methods.
    """
    logger.info("Starting orphaned SharePoint subscription cleanup job")

    sharepoint_subscription_service = container.sharepoint_subscription_service()
    sharepoint_subscription_repo = container.sharepoint_subscription_repo()

    # Get all subscriptions
    all_subscriptions = await sharepoint_subscription_repo.list_all()

    if not all_subscriptions:
        logger.info("No subscriptions to check")
        return {"deleted": 0, "skipped": 0, "failed": 0}

    logger.info(f"Checking {len(all_subscriptions)} subscriptions for orphans")

    deleted_count = 0
    skipped_count = 0
    failed_count = 0

    for subscription in all_subscriptions:
        try:
            # Check if subscription has any references
            ref_count = await sharepoint_subscription_repo.count_references(
                subscription_id=subscription.id
            )

            if ref_count > 0:
                # Still in use, skip
                skipped_count += 1
                continue

            # Orphaned subscription - delete it
            logger.info(
                f"Found orphaned subscription {subscription.subscription_id}, "
                f"site={subscription.site_id[:30]}..."
            )

            # Get token using unified helper (supports both OAuth and tenant app)
            token = await get_token_for_subscription(subscription, container)

            if not token:
                logger.warning(
                    f"Could not get token for subscription {subscription.subscription_id}, "
                    f"cannot delete from Microsoft Graph"
                )
                failed_count += 1
                continue

            # Delete subscription
            success = await sharepoint_subscription_service.delete_subscription_if_unused(
                subscription_id=subscription.id,
                token=token
            )

            if success:
                deleted_count += 1
            else:
                failed_count += 1

        except Exception as exc:
            logger.error(
                f"Error cleaning up subscription {subscription.subscription_id}: {exc}",
                exc_info=True
            )
            failed_count += 1

    logger.info(
        f"Orphaned subscription cleanup complete: {deleted_count} deleted, "
        f"{skipped_count} still in use, {failed_count} failed"
    )

    return {"deleted": deleted_count, "skipped": skipped_count, "failed": failed_count}
