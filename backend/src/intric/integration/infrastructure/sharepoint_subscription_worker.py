"""ARQ background worker for SharePoint subscription maintenance.

This worker handles:
1. Subscription renewal - runs every 3 hours to renew expiring subscriptions
2. Orphaned subscription cleanup - runs daily to remove unused subscriptions
"""

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.worker.worker import Worker

logger = get_logger(__name__)

worker = Worker()


@worker.cron_job(minute={0, 180, 360, 540})  # Every 3 hours (0, 3, 6, 9, 12, 15, 18, 21)
async def renew_expiring_subscriptions(container: Container):
    """Renew SharePoint subscriptions expiring within the next 4 hours.

    Microsoft Graph subscriptions expire after 24 hours max. We renew them
    4 hours before expiration to ensure continuous webhook notifications.

    Runs every 3 hours to catch all subscriptions before they expire.
    """
    logger.info("Starting SharePoint subscription renewal job")

    sharepoint_subscription_service = container.sharepoint_subscription_service()
    oauth_token_service = container.oauth_token_service()

    async with container.session().begin():
        # Find subscriptions expiring in next 4 hours
        expiring = await sharepoint_subscription_service.list_expiring_subscriptions(hours=4)

        if not expiring:
            logger.info("No subscriptions need renewal")
            return {"renewed": 0, "failed": 0}

        logger.info(f"Found {len(expiring)} subscriptions to renew")

        renewed_count = 0
        failed_count = 0

        for subscription in expiring:
            try:
                # Get token for this user integration
                token = await oauth_token_service.get_token_for_user_integration(
                    user_integration_id=subscription.user_integration_id
                )

                if not token:
                    logger.warning(
                        f"No token found for subscription {subscription.subscription_id}, "
                        f"user_integration={subscription.user_integration_id}"
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
    """
    logger.info("Starting orphaned SharePoint subscription cleanup job")

    sharepoint_subscription_service = container.sharepoint_subscription_service()
    sharepoint_subscription_repo = container.sharepoint_subscription_repo()
    oauth_token_service = container.oauth_token_service()

    async with container.session().begin():
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

                # Get token for deletion
                token = await oauth_token_service.get_token_for_user_integration(
                    user_integration_id=subscription.user_integration_id
                )

                if not token:
                    logger.warning(
                        f"No token found for subscription {subscription.subscription_id}, "
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
