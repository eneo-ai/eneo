"""ARQ background worker for SharePoint subscription maintenance.

This worker handles:
1. Subscription renewal - runs every 12 hours to renew expiring subscriptions
2. Orphaned subscription cleanup - runs daily to remove unused subscriptions
3. Stale sync jobs - every 30 minutes, fails sync jobs a crashed worker left
4. Sync catch-up - every 15 minutes, queues the syncs notifications missed
5. Lifecycle events - renews or recreates a subscription Graph asked about
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, cast

from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SimpleSharePointToken,
)
from eneo.integration.infrastructure.sharepoint_webhook_service import (
    LIFECYCLE_SUBSCRIPTION_REMOVED,
    SubscriptionMaintenance,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error
from eneo.worker.worker import Worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.integration.infrastructure.sharepoint_subscription_service import (
        SharePointSubscriptionService,
    )

logger = get_logger(__name__)

worker = Worker()


async def record_renewal_failure(
    subscription: SharePointSubscription,
    container: Container,
    error_message: str,
) -> None:
    """Record and persist a failed renewal attempt."""
    subscription.mark_renewal_failure(error_message)
    await persist_renewal_failure(subscription, container)


async def persist_renewal_failure(
    subscription: SharePointSubscription, container: Container
) -> None:
    """Persist renewal failure state without failing the maintenance job.

    Runs in its own SAVEPOINT so a single failure can never poison the shared
    cron transaction and silently drop later subscriptions' health writes.
    """
    try:
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


async def record_failed_attempt(
    subscription: SharePointSubscription,
    container: Container,
    error: Exception,
    *,
    failures_before: int,
) -> None:
    """Record a renewal or recreation that failed inside its savepoint.

    The savepoint has rolled back, so the transaction is clean for this
    write (which uses its own savepoint). When the service already recorded
    why a recreation failed, the rollback took that write with it, so it is
    written again rather than counted a second time.
    """
    if subscription.consecutive_renewal_failures > failures_before:
        await persist_renewal_failure(subscription, container)
    else:
        await record_renewal_failure(subscription, container, user_visible_error(error))


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
            access_token = await container.org_token_provider().get_access_token(
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


async def maintain_subscriptions(requests: list[SubscriptionMaintenance]) -> None:
    """Run the Graph calls lifecycle events asked for, each in its own transaction.

    Started once the lifecycle notification has been acknowledged, on a
    session of its own. A failure is recorded on the subscription like a
    failed renewal; the renewal cron retries before the subscription expires.
    """
    for request in requests:
        try:
            async with sessionmanager.session() as session, session.begin():
                container = Container(session=providers.Object(session))
                await _maintain_subscription(container, request)
        except Exception:
            logger.error(
                "Could not handle %s for SharePoint subscription %s",
                request.event,
                request.subscription_id,
                exc_info=True,
            )


async def _maintain_subscription(
    container: Container, request: SubscriptionMaintenance
) -> None:
    subscription = await container.sharepoint_subscription_repo().one_or_none(
        id=request.subscription_id
    )
    if subscription is None:
        return
    service = container.sharepoint_subscription_service()
    removed = request.event == LIFECYCLE_SUBSCRIPTION_REMOVED
    action = (
        "replace the subscription Microsoft Graph removed"
        if removed
        else "reauthorize the subscription Microsoft Graph asked about"
    )
    token = await get_token_for_subscription(subscription, container)
    if token is None:
        await record_renewal_failure(
            subscription, container, f"Could not get a token to {action}"
        )
        return
    session = cast("AsyncSession", container.session())
    failures_before = subscription.consecutive_renewal_failures
    try:
        # The savepoint keeps a token refreshed above when Graph refuses.
        async with session.begin_nested():
            if request.event == LIFECYCLE_SUBSCRIPTION_REMOVED:
                # Graph has deleted it; renewing is not possible.
                done = await service.recreate_expired_subscription(
                    subscription=subscription,
                    token=token,
                    is_onedrive=subscription.is_onedrive,
                )
            else:
                # A renewal reauthorizes the subscription as well.
                done = await service.renew_subscription(
                    subscription=subscription, token=token
                )
            if not done:
                raise RuntimeError(f"Microsoft Graph refused to {action}")
    except Exception as exc:
        await record_failed_attempt(
            subscription, container, exc, failures_before=failures_before
        )
        return
    if removed or failures_before:
        # Changes made while the subscription was gone, or paused because Graph
        # could not reauthorize it, were never notified.
        await queue_syncs_after_recovery(subscription, container)


@worker.cron_job(
    minute=0, hour={0, 12}, manages_own_session=True
)  # Every 12 hours (midnight and noon)
async def renew_expiring_subscriptions(container: Container):
    """Renew SharePoint subscriptions expiring within the next 48 hours.

    Microsoft Graph subscriptions expire after ~29 days max. We renew them
    48 hours (2 days) before expiration to ensure continuous webhook notifications.

    Runs every 12 hours to catch all subscriptions before they expire.

    Supports both user OAuth and tenant app authentication methods.

    Each subscription is renewed and committed in a transaction of its own. A
    renewal can recreate the subscription and delete the old one at Graph at
    once; until the new id is committed its notifications are for an unknown
    subscription, and a rollback would put back an id Graph no longer has.
    """
    logger.info("Starting SharePoint subscription renewal job")

    sharepoint_subscription_service = container.sharepoint_subscription_service()
    session = cast("AsyncSession", container.session())

    # Find subscriptions expiring in next 48 hours (2 days)
    async with session.begin():
        expiring = await sharepoint_subscription_service.list_expiring_subscriptions(
            hours=48
        )

    if not expiring:
        logger.info("No subscriptions need renewal")
        return {"renewed": 0, "failed": 0}

    logger.info(f"Found {len(expiring)} subscriptions to renew")

    renewed_count = 0
    failed_count = 0
    for subscription in expiring:
        try:
            async with session.begin():
                renewed = await _renew_one(
                    subscription, container, sharepoint_subscription_service
                )
        except Exception:
            logger.error(
                "Could not commit the renewal of subscription %s",
                subscription.subscription_id,
                exc_info=True,
            )
            renewed = False
        if renewed:
            renewed_count += 1
        else:
            failed_count += 1

    logger.info(
        f"Subscription renewal job complete: {renewed_count} renewed, {failed_count} failed"
    )

    return {"renewed": renewed_count, "failed": failed_count}


async def _renew_one(
    subscription: SharePointSubscription,
    container: Container,
    sharepoint_subscription_service: "SharePointSubscriptionService",
) -> bool:
    session = cast("AsyncSession", container.session())
    failures_before = subscription.consecutive_renewal_failures
    try:
        token = await get_token_for_subscription(subscription, container)
        if not token:
            raise RuntimeError(
                f"Could not get token for subscription {subscription.subscription_id}"
            )

        # The renewal runs in a SAVEPOINT so its DB error leaves the
        # transaction usable for the failure write. Token refresh happens
        # before it so a Graph renewal rollback cannot undo a rotated refresh
        # token.
        async with session.begin_nested():
            success = await sharepoint_subscription_service.renew_subscription(
                subscription=subscription, token=token
            )
            if not success:
                raise RuntimeError(
                    f"Renewal returned false for subscription {subscription.subscription_id}"
                )
            # Knowledge rows whose link was lost at import only receive
            # webhooks once they point at the live subscription again.
            linked = await container.sharepoint_subscription_repo().link_unreferenced_knowledge(
                subscription
            )
            if linked:
                logger.info(
                    "Linked %d knowledge row(s) to SharePoint subscription %s",
                    linked,
                    subscription.subscription_id,
                )
    except Exception as exc:
        logger.error(
            f"Error renewing subscription {subscription.subscription_id}: {exc}",
            exc_info=True,
        )
        await record_failed_attempt(
            subscription, container, exc, failures_before=failures_before
        )
        return False
    if failures_before:
        await queue_syncs_after_recovery(subscription, container)
    return True


async def queue_syncs_after_recovery(
    subscription: SharePointSubscription, container: Container
) -> None:
    """Queue a sync for the sources of a subscription that was not delivering.

    Graph pauses a subscription it could not reauthorize or renew, and
    removes one it gave up on; the changes made meanwhile are never notified.
    """
    queued = await container.sharepoint_webhook_service().queue_syncs_for_subscription(
        subscription
    )
    logger.info(
        "SharePoint subscription %s delivers again; queued %d sync(s) for the "
        "changes it missed",
        subscription.subscription_id,
        queued,
    )


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
# (see JobRepository.mark_stale_jobs_failed). A running sync holds its job row
# locked until it commits and the reaper skips locked rows, so a live sync is
# never failed and never blocks the reaper; the timeout only has to exceed a
# normal queue wait.
SHAREPOINT_SYNC_TASKS = ["pull_sharepoint_content", "sync_sharepoint_delta"]
SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES = 120


@worker.cron_job(minute={15, 45})  # Every 30 minutes, offset from renewal
async def fail_stale_sharepoint_sync_jobs(container: Container):
    """Fail SharePoint sync jobs stuck QUEUED/IN_PROGRESS past the stale timeout.

    A hard crash mid-sync (worker killed, OOM) leaves a stuck Job that arq will not
    retry and no finally fails. Because the sync commits its status only at the end,
    a crashed job reverts to QUEUED, so the reaper covers both states. Mirrors the
    crawl lease reconciler so stuck syncs surface as failures instead of hanging.
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


@worker.cron_job(
    minute={7, 22, 37, 52}, manages_own_session=True
)  # Every 15 minutes, offset from the others
async def catch_up_sharepoint_syncs(container: Container):
    """Queue the SharePoint syncs that notifications alone would have missed.

    Graph notifications are the only other trigger. Graph drops them when it
    throttles or the endpoint was unreachable, and a sync interrupted by a
    worker crash leaves its markers unread. Every source with such a marker,
    and every source with a delta token that no sync has touched for
    SHAREPOINT_CATCH_UP_AFTER_HOURS, gets a sync here (a delta, or a full
    sync when one was asked for), at most
    SHAREPOINT_CATCH_UP_MAX_SYNCS_PER_RUN per run and never while a sync of
    it runs or is queued.
    """
    settings = get_settings()
    hours = settings.sharepoint_catch_up_after_hours
    if hours <= 0:
        return {"queued": 0, "markers": 0, "stale": 0}
    window = timedelta(hours=hours)
    summary = await container.sharepoint_webhook_service().queue_catch_up_syncs(
        stale_before=datetime.now(timezone.utc) - window,
        limit=settings.sharepoint_catch_up_max_syncs_per_run,
        window_seconds=int(window.total_seconds()),
    )
    if summary["queued"]:
        logger.info(
            "SharePoint catch-up queued %d sync(s): %d for unread markers, "
            "%d for sources without a sync in %d hours",
            summary["queued"],
            summary["markers"],
            summary["stale"],
            hours,
        )
    return summary
