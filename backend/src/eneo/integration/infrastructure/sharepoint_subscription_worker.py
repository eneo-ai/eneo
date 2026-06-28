"""ARQ background worker for SharePoint subscription maintenance.

This worker handles:
1. Subscription renewal - runs every 12 hours to renew expiring subscriptions
2. Orphaned subscription cleanup - runs daily to remove unused subscriptions
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, cast

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SimpleSharePointToken,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.worker.worker import Worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

worker = Worker()


async def record_renewal_failure(
    subscription: SharePointSubscription,
    container: Container,
    error_message: str,
) -> None:
    """Persist renewal failure state without failing the maintenance job.

    Runs in its own SAVEPOINT so a single failure can never poison the shared
    cron transaction and silently drop later subscriptions' health writes.
    """
    try:
        subscription.mark_renewal_failure(error_message)
        session = cast("AsyncSession", container.session())
        async with session.begin_nested():
            await container.sharepoint_subscription_repo().update(subscription)
    except Exception as exc:
        logger.error(
            "Failed to record renewal failure for subscription %s: %s",
            subscription.subscription_id,
            exc,
            exc_info=True,
        )


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
        user_integration = await user_integration_repo.one(
            id=subscription.user_integration_id
        )
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
            tenant_app = await tenant_sharepoint_app_repo.one(
                id=user_integration.tenant_app_id
            )

            if tenant_app.is_service_account():
                service_account_auth_service = container.service_account_auth_service()
                token_data = await service_account_auth_service.refresh_access_token(
                    tenant_app
                )
                new_refresh_token = token_data.get("refresh_token")
                if (
                    new_refresh_token
                    and new_refresh_token != tenant_app.service_account_refresh_token
                ):
                    tenant_app.update_refresh_token(new_refresh_token)
                    await tenant_sharepoint_app_repo.update(tenant_app)
                access_token = token_data["access_token"]
            else:
                tenant_app_auth_service = container.tenant_app_auth_service()
                access_token = await tenant_app_auth_service.get_access_token(
                    tenant_app
                )

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
            token = await oauth_token_service.refresh_and_update_token(
                token_id=token.id
            )
            return token  # type: ignore[return-value]

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
    expiring = await sharepoint_subscription_service.list_expiring_subscriptions(
        hours=48
    )

    if not expiring:
        logger.info("No subscriptions need renewal")
        return {"renewed": 0, "failed": 0}

    logger.info(f"Found {len(expiring)} subscriptions to renew")

    renewed_count = 0
    failed_count = 0
    session = cast("AsyncSession", container.session())

    for subscription in expiring:
        try:
            token = await get_token_for_subscription(subscription, container)
            if not token:
                raise RuntimeError(
                    f"Could not get token for subscription {subscription.subscription_id}"
                )

            # Isolate each renewal in a SAVEPOINT so one subscription's DB error
            # cannot poison the shared cron transaction and drop the rest. Token
            # refresh happens before this savepoint so a Graph renewal rollback
            # cannot undo a rotated refresh token.
            async with session.begin_nested():
                success = await sharepoint_subscription_service.renew_subscription(
                    subscription=subscription, token=token
                )
                if not success:
                    raise RuntimeError(
                        f"Renewal returned false for subscription {subscription.subscription_id}"
                    )
            renewed_count += 1

        except Exception as exc:
            logger.error(
                f"Error renewing subscription {subscription.subscription_id}: {exc}",
                exc_info=True,
            )
            # The savepoint above has rolled back, so the transaction is clean for
            # this failure write (which uses its own savepoint).
            await record_renewal_failure(subscription, container, str(exc))
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
            resource_id = subscription.site_id or subscription.drive_id or "unknown"
            logger.info(
                f"Found orphaned subscription {subscription.subscription_id}, "
                f"resource={resource_id[:30]}..."
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
            success = (
                await sharepoint_subscription_service.delete_subscription_if_unused(
                    subscription_id=subscription.id, token=token
                )
            )

            if success:
                deleted_count += 1
            else:
                failed_count += 1

        except Exception as exc:
            logger.error(
                f"Error cleaning up subscription {subscription.subscription_id}: {exc}",
                exc_info=True,
            )
            failed_count += 1

    logger.info(
        f"Orphaned subscription cleanup complete: {deleted_count} deleted, "
        f"{skipped_count} still in use, {failed_count} failed"
    )

    return {"deleted": deleted_count, "skipped": skipped_count, "failed": failed_count}


# SharePoint sync tasks that can leave a stuck Job if the worker dies mid-run (arq
# does not retry these and there is no per-task finally that fails the Job). Each
# task runs its whole body in ONE transaction committed only at the end, so a hard
# crash rolls back the in-flight IN_PROGRESS write and the row reverts to its last
# committed state (QUEUED). The reaper therefore targets BOTH QUEUED and IN_PROGRESS
# (see JobRepository.mark_stale_jobs_failed). The timeout must exceed the longest
# legitimate full sync of a large site AND any normal queue wait, so a slow-but-live
# job is never killed.
SHAREPOINT_SYNC_TASKS = ["pull_sharepoint_content", "sync_sharepoint_delta"]
SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES = 120


@worker.cron_job(minute={15, 45})  # Every 30 minutes, offset from renewal
async def fail_stale_sharepoint_sync_jobs(container: Container):
    """Fail SharePoint sync jobs stuck QUEUED/IN_PROGRESS past the stale timeout.

    A hard crash mid-sync (worker killed, OOM) leaves a stuck Job that arq will not
    retry and no finally fails. Because the sync commits its status only at the end,
    a crashed job reverts to QUEUED, so the reaper covers both states. Mirrors the
    crawl OrphanWatchdog so stuck syncs surface as failures instead of hanging.
    """
    stale_before = datetime.now(timezone.utc) - timedelta(
        minutes=SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES
    )
    job_repo = container.job_repo()
    failed_ids = await job_repo.mark_stale_jobs_failed(
        tasks=SHAREPOINT_SYNC_TASKS,
        stale_before=stale_before,
    )

    if failed_ids:
        logger.warning(
            "Failed %d stale SharePoint sync job(s) (QUEUED/IN_PROGRESS): %s",
            len(failed_ids),
            [str(job_id) for job_id in failed_ids],
        )

    return {"failed_stale_jobs": len(failed_ids)}
