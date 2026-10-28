from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.integration_table import (
    Integration,
    TenantIntegration,
)
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.database.tables.tenant_sharepoint_app_table import TenantSharePointApp
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.domain.repositories.oauth_token_repo import OauthTokenRepository
from eneo.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionRepository,
)
from eneo.integration.domain.task_params import SharepointContentTaskParam
from eneo.integration.infrastructure.connection_owner import owner_can_sign_in
from eneo.integration.infrastructure.content_service.types import (
    SharePointWebhookNotification,
    SharePointWebhookPayload,
)
from eneo.integration.infrastructure.detached_tasks import run_detached
from eneo.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    claim_sync_queue_slot,
    leave_marker,
    marker_then_recheck,
    release_sync_queue_slot,
    sync_catch_up_key,
    sync_catch_up_marker_key,
    sync_lock_key,
    sync_pending_full_key,
    sync_pending_key,
    sync_queued_key,
)
from eneo.jobs.job_models import Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_service import JobService
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.tenants.tenant import TenantState
from eneo.users.user import UserInDB
from eneo.users.user_repo import UsersRepository

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


def client_state_matches(expected: str | None, value: object) -> bool:
    """Constant-time comparison of a notification's clientState with the secret.

    Compared as UTF-8 bytes: ``hmac.compare_digest`` refuses non-ASCII text,
    which would turn a forged ``clientState`` into a 500 and break every
    notification for a secret containing one.
    """
    if not expected or not isinstance(value, str):
        return False
    return hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


LIFECYCLE_MISSED = "missed"
LIFECYCLE_REAUTHORIZATION_REQUIRED = "reauthorizationRequired"
LIFECYCLE_SUBSCRIPTION_REMOVED = "subscriptionRemoved"
_MAINTENANCE_WINDOW_SECONDS = 10 * 60
# A marker stands for a known change, so it is retried sooner than a source
# that is only stale.
_MARKER_CATCH_UP_WINDOW_SECONDS = 60 * 60
# Catch-up reads the sync state of this many sources per Redis round trip.
_SYNC_STATE_BATCH = 500


@dataclass(frozen=True)
class SubscriptionMaintenance:
    """A Graph call a lifecycle event asks for, run after the acknowledgement."""

    subscription_id: UUID
    event: str


@dataclass(frozen=True)
class _CatchUpCandidate:
    id: UUID
    has_delta_token: bool
    last_activity: datetime


@dataclass(frozen=True)
class _SyncState:
    running: bool
    queued: bool
    full_requested: bool
    delta_requested: bool
    recently_caught_up: bool
    marker_recently_caught_up: bool


@dataclass
class _QueueContext:
    """Per-call caches: one tenant admin or user lookup and one JobService each."""

    users: dict[str, UserInDB] = field(default_factory=lambda: {})
    job_services: dict[str, JobService] = field(default_factory=lambda: {})


class SharepointWebhookService:
    """Handles callbacks from Microsoft Graph change notifications.

    Uses ChangeKey validation (similar to ETag) to detect if items have
    actually changed, preventing duplicate processing of duplicate webhooks
    from Microsoft Graph.
    """

    def __init__(
        self,
        session: AsyncSession,
        oauth_token_repo: OauthTokenRepository,
        job_repo: JobRepository,
        user_repo: UsersRepository,
        change_key_service: OfficeChangeKeyService,
        sharepoint_subscription_repo: SharePointSubscriptionRepository,
        redis_client: "aioredis.Redis",
    ) -> None:
        super().__init__()
        self.session = session
        self.oauth_token_repo = oauth_token_repo
        self.job_repo = job_repo
        self.user_repo = user_repo
        self.change_key_service = change_key_service
        self.sharepoint_subscription_repo = sharepoint_subscription_repo
        self.redis_client = redis_client
        settings = get_settings()
        # Stripped once, as the subscription service sends it to Graph; a
        # trailing newline in the environment must not drop every notification.
        configured = settings.sharepoint_webhook_client_state
        self.expected_client_state: str | None = (
            configured.strip() if configured else None
        )

    def authenticated_notifications(
        self, notifications: SharePointWebhookPayload
    ) -> list[SharePointWebhookNotification]:
        """The notifications whose ``clientState`` matches the configured secret.

        clientState is the only authentication for this endpoint (it is
        unauthenticated at the HTTP layer). Fail closed: without a configured
        secret genuine Graph notifications cannot be told from forged ones, so
        none is accepted. Elements that are not objects are skipped. The
        endpoint is public, so rejections are summarised in one log line per
        call rather than one per element.
        """
        values = cast(list[object], notifications.get("value") or [])
        if not values:
            logger.debug("SharePoint webhook called without notifications")
            return []
        if not self.expected_client_state:
            logger.error(
                "Rejecting SharePoint webhook: SHAREPOINT_WEBHOOK_CLIENT_STATE is "
                "not configured, so notifications cannot be authenticated."
            )
            return []
        accepted: list[SharePointWebhookNotification] = []
        wrong_client_state = 0
        not_objects = 0
        for element in values:
            if not isinstance(element, dict):
                not_objects += 1
                continue
            notification = cast(SharePointWebhookNotification, element)
            if not client_state_matches(
                self.expected_client_state, notification.get("clientState")
            ):
                wrong_client_state += 1
                continue
            accepted.append(notification)
        if wrong_client_state or not_objects:
            logger.warning(
                "Ignoring %d of %d SharePoint webhook notification(s): %d with an "
                "unexpected clientState (forged, or SHAREPOINT_WEBHOOK_CLIENT_STATE "
                "differs from the subscriptions'), %d not objects",
                wrong_client_state + not_objects,
                len(values),
                wrong_client_state,
                not_objects,
            )
        return accepted

    async def handle_notifications(
        self, notifications: list[SharePointWebhookNotification]
    ) -> list[SubscriptionMaintenance]:
        """Queue syncs for notifications ``authenticated_notifications`` accepted.

        Notifications are routed by their ``subscriptionId`` to the stored
        subscription and from there to the knowledge rows referencing it, so a
        notification can only ever reach the tenant that created the
        subscription. ChangeKey-based deduplication prevents processing of
        duplicate notifications.

        Lifecycle notifications (those with a ``lifecycleEvent``) concern the
        subscription rather than a change. ``missed`` queues a sync for every
        knowledge row on the subscription, since Graph says it dropped
        notifications. ``reauthorizationRequired`` and ``subscriptionRemoved``
        need calls to Graph, which are returned for the caller to run once the
        notification has been acknowledged.
        """
        by_subscription: dict[str, list[SharePointWebhookNotification]] = {}
        lifecycle: list[tuple[str, str]] = []
        for notification in notifications:
            subscription_id = notification.get("subscriptionId")
            if not isinstance(subscription_id, str) or not subscription_id:
                logger.warning("Ignoring webhook notification without subscriptionId")
                continue
            event = cast(dict[str, object], notification).get("lifecycleEvent")
            if event is not None:
                lifecycle.append((subscription_id, str(event)))
                continue
            by_subscription.setdefault(subscription_id, []).append(notification)

        for subscription_id, subscription_notifications in by_subscription.items():
            subscription = (
                await self.sharepoint_subscription_repo.get_by_subscription_id(
                    subscription_id
                )
            )
            if subscription is None:
                logger.info(
                    "Ignoring SharePoint webhook for unknown subscription %s",
                    subscription_id,
                )
                continue
            await self._mark_subscription_webhook_received(subscription)
            await self._queue_refresh_for_subscription(
                subscription=subscription,
                notifications=subscription_notifications,
            )
        return await self._handle_lifecycle_events(lifecycle)

    async def _handle_lifecycle_events(
        self, events: list[tuple[str, str]]
    ) -> list[SubscriptionMaintenance]:
        maintenance: list[SubscriptionMaintenance] = []
        handled: set[tuple[str, str]] = set()
        for subscription_id, event in events:
            if (subscription_id, event) in handled:
                continue
            handled.add((subscription_id, event))
            subscription = (
                await self.sharepoint_subscription_repo.get_by_subscription_id(
                    subscription_id
                )
            )
            if subscription is None:
                logger.info(
                    "Ignoring SharePoint lifecycle event %s for unknown subscription %s",
                    event[:40],
                    subscription_id,
                )
                continue
            if event == LIFECYCLE_MISSED:
                logger.warning(
                    "Graph dropped notifications for SharePoint subscription %s; "
                    "queuing a sync for its knowledge",
                    subscription_id,
                )
                await self.queue_syncs_for_subscription(subscription)
            elif event in (
                LIFECYCLE_REAUTHORIZATION_REQUIRED,
                LIFECYCLE_SUBSCRIPTION_REMOVED,
            ):
                if await self._claim_maintenance(subscription.id, event):
                    logger.info(
                        "Graph sent %s for SharePoint subscription %s",
                        event,
                        subscription_id,
                    )
                    maintenance.append(SubscriptionMaintenance(subscription.id, event))
            else:
                logger.info(
                    "Ignoring unknown SharePoint lifecycle event %s for subscription %s",
                    event[:40],
                    subscription_id,
                )
        return maintenance

    async def _claim_maintenance(self, subscription_db_id: UUID, event: str) -> bool:
        """At most one Graph call per subscription and event in a window.

        Graph repeats ``reauthorizationRequired`` as expiry nears, and asks
        apps not to renew a subscription twice within ten minutes. Without
        Redis nothing is claimed: the renewal cron still renews the
        subscription, and a burst of events cannot each call Graph.
        """
        try:
            return bool(
                await self.redis_client.set(
                    f"sharepoint_subscription_maintenance:{subscription_db_id}:{event}",
                    "1",
                    nx=True,
                    ex=_MAINTENANCE_WINDOW_SECONDS,
                )
            )
        except (RedisError, OSError) as exc:
            logger.warning(
                "Could not check recent maintenance of subscription %s (%s)",
                subscription_db_id,
                type(exc).__name__,
            )
            return False

    async def queue_syncs_for_subscription(
        self, subscription: SharePointSubscription
    ) -> int:
        """Queue a sync for every knowledge row on a subscription; returns how many.

        For when Graph says changes went unnotified: they may be anywhere in
        the drive, so every row is in scope. A row being synced gets a marker
        instead of a job, as for any notification.
        """
        if subscription.is_onedrive:
            fallback = ("drive", subscription.drive_id)
        else:
            fallback = ("site", subscription.site_id)
        context = _QueueContext()
        queued = 0
        for (
            knowledge_db,
            user_integration_db,
        ) in await self._fetch_knowledge_by_subscription(subscription.id):
            if await self._deferred_to_running_sync(str(knowledge_db.id)):
                continue
            if await self._queue_sync(
                knowledge_db,
                user_integration_db,
                context=context,
                fallback_resource=fallback,
            ):
                queued += 1
        return queued

    async def _mark_subscription_webhook_received(
        self, subscription: SharePointSubscription
    ) -> None:
        try:
            subscription.mark_webhook_received()
            await self.sharepoint_subscription_repo.update(subscription)
        except Exception as exc:
            logger.warning(
                "Could not update SharePoint subscription webhook health for %s: %s",
                subscription.subscription_id,
                exc,
            )

    async def _queue_refresh_for_subscription(
        self,
        subscription: SharePointSubscription,
        notifications: list[SharePointWebhookNotification],
    ) -> None:
        """Queue refresh jobs for the knowledge rows referencing a subscription.

        Validates each notification's ChangeKey before queuing to prevent
        processing duplicates. Filters integrations by scope to avoid
        unnecessary syncs for file/folder-level integrations.
        """
        if subscription.is_onedrive:
            resource_type, resource_id = "drive", subscription.drive_id
        else:
            resource_type, resource_id = "site", subscription.site_id

        knowledge_records = await self._fetch_knowledge_by_subscription(subscription.id)
        if not knowledge_records:
            logger.info(
                "No integration knowledge that may sync references SharePoint "
                "subscription %s (%s %s)",
                subscription.subscription_id,
                resource_type,
                resource_id,
            )
            return

        context = _QueueContext()
        queued_knowledge: set[str] = set()

        # Deduplicate per subscription: two subscriptions on the same site get
        # their own Graph notifications for one change, and each must still
        # reach its own knowledge rows.
        unique_notifications: list[SharePointWebhookNotification] = []
        dedupe_key = f"subscription:{subscription.id}"
        dedupe_integration_knowledge_id = uuid5(NAMESPACE_URL, dedupe_key)
        for notification in notifications:
            resource_data = cast(
                dict[str, str],
                notification.get("resourceData") or {},
            )
            item_id = resource_data.get("id")
            change_key = notification.get("changeKey") or resource_data.get("changeKey")

            if not item_id or not change_key:
                # Missing data - include it (fail-safe)
                unique_notifications.append(notification)
                continue

            should_include = await self.change_key_service.should_process(
                integration_knowledge_id=dedupe_integration_knowledge_id,
                item_id=item_id,
                change_key=change_key,
            )

            if should_include:
                unique_notifications.append(notification)
                await self.change_key_service.update_change_key(
                    integration_knowledge_id=dedupe_integration_knowledge_id,
                    item_id=item_id,
                    change_key=change_key,
                )
                logger.info(
                    f"{resource_type} {resource_id}: Notification for item {item_id} passed deduplication (new or changed)"
                )
            else:
                logger.info(
                    f"{resource_type} {resource_id}: Skipping duplicate notification for item {item_id} (ChangeKey unchanged)"
                )

        if not unique_notifications:
            logger.info(
                f"{resource_type} {resource_id}: All notifications were duplicates, nothing to sync"
            )
            return

        for knowledge_db, user_integration_db in knowledge_records:
            # Skip if we've already queued a job for this knowledge in this webhook
            knowledge_id_str = str(knowledge_db.id)
            if knowledge_id_str in queued_knowledge:
                logger.info(
                    f"Skipping duplicate queue for integration knowledge {knowledge_id_str}"
                )
                continue

            # Check if ANY of the unique notifications are in scope for this integration
            should_process_any = False
            for notification in unique_notifications:
                # Check if the changed item is in this integration's scope
                in_scope = self._is_notification_in_scope(
                    notification=notification,
                    knowledge_db=knowledge_db,
                )
                if in_scope:
                    should_process_any = True
                    logger.info(
                        f"Knowledge {knowledge_id_str}: Notification IS IN SCOPE - will queue sync"
                    )
                    break
                else:
                    logger.info(
                        f"Knowledge {knowledge_id_str}: Notification NOT IN SCOPE - skipping"
                    )

            if not should_process_any:
                logger.info(
                    f"Knowledge {knowledge_id_str}: No changes in scope detected. Will NOT queue sync."
                )
                continue

            if await self._deferred_to_running_sync(knowledge_id_str):
                queued_knowledge.add(knowledge_id_str)
                continue

            if await self._queue_sync(
                knowledge_db,
                user_integration_db,
                context=context,
                fallback_resource=(resource_type, resource_id),
            ):
                queued_knowledge.add(knowledge_id_str)

    async def queue_sync_for_knowledge(
        self, knowledge_id: UUID, *, full: bool = False
    ) -> Task | None:
        """Queue a sync for one knowledge row the way a notification would.

        For syncs no request asked for: the follow-up a sync task queues for
        markers left during its lease, and the periodic catch-up. ``full``
        asks for a full sync even when the knowledge has a delta token.
        Returns the task queued, or None when nothing was queued.
        """
        records = await self._fetch_knowledge(
            IntegrationKnowledgeDBModel.id == knowledge_id
        )
        if not records:
            logger.info(
                "Not queuing a sync for knowledge %s: it no longer exists, or "
                "its connection's owner can no longer sign in",
                knowledge_id,
            )
            return None
        knowledge_db, user_integration_db = records[0]
        return await self._queue_sync(
            knowledge_db, user_integration_db, context=_QueueContext(), full=full
        )

    async def _queue_sync(
        self,
        knowledge_db: IntegrationKnowledgeDBModel,
        user_integration_db: UserIntegrationDBModel,
        *,
        context: "_QueueContext",
        full: bool = False,
        fallback_resource: tuple[str, str] | None = None,
    ) -> Task | None:
        """Queue one sync job for a knowledge row; None when nothing was queued.

        The job runs with the connection's own credentials: the tenant app,
        or the OAuth token of the person who connected. ``fallback_resource``
        is the notified subscription's (kind, id), used when the row lacks
        its own site or drive id.
        """
        knowledge_id_str = str(knowledge_db.id)
        # Validate that user_integration_db.id is not None before proceeding
        # (id is always populated from DB; this guards against unexpected None)
        ui_id = user_integration_db.id
        if ui_id is None:  # pyright: ignore[reportUnnecessaryComparison]  # defensive guard: DB id is non-null in practice
            logger.error(
                "user_integration_db.id is None for knowledge %s; skipping",
                knowledge_db.id,
            )
            return None

        # Determine authentication method and fetch appropriate credentials
        # For tenant_app integrations: use tenant_app_id, no OAuth token
        # For user_oauth integrations: use OAuth token, no tenant_app_id
        token_id: UUID | None = None
        tenant_app_id: UUID | None = None

        if user_integration_db.auth_type == "tenant_app":
            # Tenant app integration - no OAuth token needed
            # The worker task will fetch tenant app credentials using tenant_app_id
            tenant_app_id = user_integration_db.tenant_app_id
            if not tenant_app_id:
                logger.warning(
                    "Tenant app integration %s has no tenant_app_id; skipping",
                    user_integration_db.id,
                )
                return None
            logger.info(
                f"Using tenant app {tenant_app_id} for integration {user_integration_db.id}"
            )
        else:
            # User OAuth integration - fetch OAuth token
            token = await self.oauth_token_repo.one_or_none(
                user_integration_id=user_integration_db.id
            )
            if not token:
                logger.warning(
                    "No OAuth token found for user integration %s; skipping",
                    user_integration_db.id,
                )
                return None
            token_id = token.id
            logger.info(
                f"Using OAuth token {token_id} for integration {user_integration_db.id}"
            )

        # Determine which user to use for job creation
        # For tenant_app integrations (user_id=None), use a tenant admin
        # For user_oauth integrations, use the specific user
        user_cache = context.users
        if user_integration_db.user_id is None:
            # Tenant app integration - person-independent
            # Use a tenant admin for job creation
            cache_key = f"tenant_admin_{user_integration_db.tenant_id}"
            if cache_key not in user_cache:
                try:
                    admin_user = await self._get_tenant_admin(
                        user_integration_db.tenant_id
                    )
                    user_cache[cache_key] = admin_user
                    logger.info(
                        f"Using tenant admin {admin_user.id} for tenant_app integration {user_integration_db.id}"
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not load tenant admin for tenant %s: %s",
                        user_integration_db.tenant_id,
                        exc,
                    )
                    return None
            user_for_job = user_cache[cache_key]
            user_id_for_job = user_for_job.id
            job_service_key = cache_key
        else:
            # User OAuth integration - use the specific user
            user_id_str = str(user_integration_db.user_id)
            if user_id_str not in user_cache:
                try:
                    loaded_user = await self.user_repo.get_user_by_id(
                        id=user_integration_db.user_id
                    )
                    if loaded_user is None:
                        raise ValueError(
                            f"User {user_integration_db.user_id} not found"
                        )
                    user_cache[user_id_str] = loaded_user
                except Exception as exc:
                    logger.warning(
                        "Could not load user %s for SharePoint webhook notification: %s",
                        user_integration_db.user_id,
                        exc,
                    )
                    return None
            user_for_job = user_cache[user_id_str]
            user_id_for_job = user_integration_db.user_id
            job_service_key = user_id_str

        resource_type, resource_id = fallback_resource or (
            ("drive", knowledge_db.drive_id)
            if knowledge_db.resource_type == "onedrive"
            else ("site", knowledge_db.site_id)
        )
        site_id_value = (
            knowledge_db.site_id if isinstance(knowledge_db.site_id, str) else None
        )
        drive_id_value = (
            knowledge_db.drive_id if isinstance(knowledge_db.drive_id, str) else None
        )
        resource_type_value = (
            knowledge_db.resource_type
            if isinstance(knowledge_db.resource_type, str)
            and knowledge_db.resource_type in {"site", "onedrive"}
            else None
        )
        site_id_param = site_id_value or (
            resource_id if resource_type == "site" else None
        )
        drive_id_param = drive_id_value or (
            resource_id if resource_type == "drive" else None
        )
        if not site_id_param and not drive_id_param:
            logger.warning(
                "Knowledge %s has no site or drive to sync; skipping",
                knowledge_id_str,
            )
            return None

        params = SharepointContentTaskParam(
            user_id=user_id_for_job,
            id=ui_id,
            token_id=token_id,  # None for tenant_app, UUID for user_oauth
            tenant_app_id=tenant_app_id,  # UUID for tenant_app, None for user_oauth
            integration_knowledge_id=knowledge_db.id,
            site_id=site_id_param,
            drive_id=drive_id_param,
            folder_id=knowledge_db.folder_id,
            folder_path=knowledge_db.folder_path,
            resource_type=resource_type_value
            or ("onedrive" if resource_type == "drive" else "site"),
        )

        if job_service_key not in context.job_services:
            context.job_services[job_service_key] = JobService(
                user=user_for_job,
                job_repo=self.job_repo,
            )

        # Use delta sync if we have a delta token, otherwise do full sync
        task_type = (
            Task.SYNC_SHAREPOINT_DELTA
            if knowledge_db.delta_token and not full
            else Task.PULL_SHAREPOINT_CONTENT
        )

        if not await claim_sync_queue_slot(self.redis_client, knowledge_id_str):
            # The queued job starts after this change and its pass covers it,
            # removing the marker as it starts. The marker stays if that job
            # never runs (lost delivery, worker gone), and the catch-up serves
            # it once the queued-sync marker has expired.
            await leave_marker(self.redis_client, knowledge_id_str, full=full)
            logger.info(
                "Knowledge %s already has a sync queued; left a marker instead of "
                "queuing another",
                knowledge_id_str,
            )
            return None
        try:
            await context.job_services[job_service_key].queue_job(
                task=task_type,
                name=knowledge_db.name or f"SharePoint ({resource_id})",
                task_params=params,
                after_commit=True,
            )
        except Exception:
            await release_sync_queue_slot(self.redis_client, knowledge_id_str)
            raise
        self._release_queue_slot_on_rollback(knowledge_id_str)

        logger.info(
            f"Queued {task_type.value} task for integration knowledge {knowledge_id_str} "
            f"({resource_type}_id={resource_id})"
        )
        return task_type

    async def queue_catch_up_syncs(
        self, *, stale_before: datetime, limit: int, window_seconds: int
    ) -> dict[str, int]:
        """Queue the syncs notifications should have led to but did not.

        Two kinds of SharePoint source get a job, at most ``limit`` in all and
        none while a sync of it runs or is queued: one with a marker that no
        sync is left to read (its sync was interrupted, or the follow-up could
        not be queued), and one with a delta token that no sync has touched
        since ``stale_before`` (Graph dropped or never sent its
        notifications). A source queued for being stale is not queued for it
        again within ``window_seconds``, and one queued for a marker not
        within the marker window, whatever became of that attempt; a source
        that cannot be queued is retried once per window, not on every run.

        Only sources whose tenant is active and whose connection can still
        authenticate are considered: an active tenant app whose credentials
        did not fail last, or the OAuth connection of a user who can still
        sign in.

        Each source is queued in a transaction of its own on this service's
        session, which must have none open: one that fails is logged and
        does not hold up the others.
        """
        async with self.session.begin():
            candidates = await self._catch_up_candidates()
        states = await self._sync_states([str(c.id) for c in candidates])
        with_markers: list[_CatchUpCandidate] = []
        stale: list[_CatchUpCandidate] = []
        for candidate in candidates:
            state = states[str(candidate.id)]
            if state.running or state.queued:
                continue
            if state.full_requested or state.delta_requested:
                if not state.marker_recently_caught_up:
                    with_markers.append(candidate)
            elif (
                candidate.has_delta_token
                and candidate.last_activity < stale_before
                and not state.recently_caught_up
            ):
                stale.append(candidate)
        with_markers.sort(key=lambda c: c.last_activity)
        stale.sort(key=lambda c: c.last_activity)
        picked = (with_markers + stale)[:limit]
        summary = {"queued": 0, "markers": 0, "stale": 0}
        stale_ids = {c.id for c in stale}
        context = _QueueContext()
        for candidate in picked:
            knowledge_id_str = str(candidate.id)
            is_stale = candidate.id in stale_ids
            # Set first, so a source whose queueing fails waits its window too.
            await self.redis_client.set(
                (sync_catch_up_key if is_stale else sync_catch_up_marker_key)(
                    knowledge_id_str
                ),
                "1",
                ex=window_seconds if is_stale else _MARKER_CATCH_UP_WINDOW_SECONDS,
            )
            try:
                async with self.session.begin():
                    records = await self._fetch_knowledge(
                        IntegrationKnowledgeDBModel.id == candidate.id
                    )
                    if not records:
                        continue
                    queued = await self._queue_sync(
                        *records[0],
                        context=context,
                        full=states[knowledge_id_str].full_requested,
                    )
            except Exception:
                logger.error(
                    "SharePoint catch-up could not queue a sync for knowledge %s",
                    knowledge_id_str,
                    exc_info=True,
                )
                continue
            if queued is None:
                continue
            summary["queued"] += 1
            summary["stale" if is_stale else "markers"] += 1
        return summary

    async def _catch_up_candidates(self) -> list[_CatchUpCandidate]:
        knowledge = IntegrationKnowledgeDBModel
        connection = UserIntegrationDBModel
        last_activity = sa.func.coalesce(
            sa.func.greatest(
                knowledge.last_sync_attempted_at, knowledge.last_synced_at
            ),
            knowledge.created_at,
        )
        stmt = (
            sa.select(
                knowledge.id,
                knowledge.delta_token.is_not(None).label("has_delta_token"),
                last_activity.label("last_activity"),
            )
            .join(connection, knowledge.user_integration_id == connection.id)
            .join(
                TenantIntegration,
                connection.tenant_integration_id == TenantIntegration.id,
            )
            .join(Integration, TenantIntegration.integration_id == Integration.id)
            .join(Tenants, connection.tenant_id == Tenants.id)
            .outerjoin(
                TenantSharePointApp, connection.tenant_app_id == TenantSharePointApp.id
            )
            .outerjoin(Users, connection.user_id == Users.id)
            .where(
                Integration.integration_type == "sharepoint",
                connection.authenticated.is_(True),
                Tenants.state == TenantState.ACTIVE.value,
                sa.or_(knowledge.site_id.is_not(None), knowledge.drive_id.is_not(None)),
                sa.or_(
                    sa.and_(
                        connection.auth_type == "tenant_app",
                        TenantSharePointApp.is_active.is_(True),
                        # As TenantSharePointApp.auth_status: the credentials
                        # failed last. A sync now would fail the same way; the
                        # next successful sign-in (a manual or notified sync, a
                        # renewal) brings the source back.
                        sa.not_(
                            sa.and_(
                                TenantSharePointApp.last_auth_error_at.is_not(None),
                                sa.or_(
                                    TenantSharePointApp.last_auth_success_at.is_(None),
                                    TenantSharePointApp.last_auth_error_at
                                    >= TenantSharePointApp.last_auth_success_at,
                                ),
                            )
                        ),
                    ),
                    sa.and_(
                        connection.auth_type == "user_oauth",
                        owner_can_sign_in(),
                    ),
                ),
            )
        )
        result = await self.session.execute(stmt)
        return [
            _CatchUpCandidate(
                id=row.id,
                has_delta_token=bool(row.has_delta_token),
                last_activity=row.last_activity,
            )
            for row in result.all()
        ]

    async def _sync_states(self, knowledge_ids: list[str]) -> dict[str, _SyncState]:
        keys = (
            sync_lock_key,
            sync_queued_key,
            sync_pending_full_key,
            sync_pending_key,
            sync_catch_up_key,
            sync_catch_up_marker_key,
        )
        states: dict[str, _SyncState] = {}
        for start in range(0, len(knowledge_ids), _SYNC_STATE_BATCH):
            batch = knowledge_ids[start : start + _SYNC_STATE_BATCH]
            async with self.redis_client.pipeline(transaction=False) as pipe:
                for knowledge_id in batch:
                    for key in keys:
                        pipe.exists(key(knowledge_id))
                flags = [bool(flag) for flag in await pipe.execute()]
            for index, knowledge_id in enumerate(batch):
                running, queued, full, delta, caught_up, marker_caught_up = flags[
                    index * len(keys) : (index + 1) * len(keys)
                ]
                states[knowledge_id] = _SyncState(
                    running=running,
                    queued=queued,
                    full_requested=full,
                    delta_requested=delta,
                    recently_caught_up=caught_up,
                    marker_recently_caught_up=marker_caught_up,
                )
        return states

    def _release_queue_slot_on_rollback(self, knowledge_id: str) -> None:
        """A job rolled back with the transaction must not block the next one."""
        session = cast(object, self.session)
        if not isinstance(session, AsyncSession):
            return

        async def committed() -> None:
            return None

        def rolled_back() -> None:
            run_detached(release_sync_queue_slot(self.redis_client, knowledge_id))

        after_outer_transaction(
            session.sync_session, on_commit=committed, on_rollback=rolled_back
        )

    async def _deferred_to_running_sync(self, knowledge_id: str) -> bool:
        """Leave the pending marker instead of a job while a sync holds the lease.

        Graph sends several notifications per change and most carry no item
        id, so each would otherwise queue a job that finds the lease taken and
        ends as skipped. The marker makes the lease holder run one more delta
        pass before releasing, which is what the skipped job would have asked
        for. Without Redis the job is queued as before.

        A marker that the holder may not read (``marker_then_recheck``) is
        served by the job queued now.
        """
        try:
            if not await self.redis_client.exists(sync_lock_key(knowledge_id)):
                return False
        except (RedisError, OSError) as exc:
            logger.warning(
                "Could not check the sync lease for knowledge %s (%s); queuing a job",
                knowledge_id,
                type(exc).__name__,
            )
            return False
        if not await marker_then_recheck(self.redis_client, knowledge_id):
            return False
        logger.info(
            "Knowledge %s is being synced; left a pending marker for the lease "
            "holder instead of queuing a job",
            knowledge_id,
        )
        return True

    async def _get_tenant_admin(self, tenant_id: UUID) -> UserInDB:
        """Get a tenant admin user for creating jobs for tenant_app integrations.

        Tenant app integrations are person-independent (user_id=None), but jobs
        still require a user context. We use a tenant admin for this purpose.

        Args:
            tenant_id: The tenant ID

        Returns:
            A tenant admin user

        Raises:
            Exception: If no admin user is found for the tenant
        """
        admins = await self.user_repo.list_tenant_admins(tenant_id=tenant_id)
        if not admins:
            raise Exception(f"No admin users found for tenant {tenant_id}")

        # The oldest admin, the same one every time: the job runs as this user,
        # so a provider's outbound headers carry this admin's attributes.
        return admins[0]

    async def _fetch_knowledge_by_subscription(
        self, subscription_db_id: UUID
    ) -> list[tuple[IntegrationKnowledgeDBModel, UserIntegrationDBModel]]:
        return await self._fetch_knowledge(
            IntegrationKnowledgeDBModel.sharepoint_subscription_id == subscription_db_id
        )

    async def _fetch_knowledge(
        self, condition: sa.ColumnElement[bool]
    ) -> list[tuple[IntegrationKnowledgeDBModel, UserIntegrationDBModel]]:
        """The rows matching ``condition`` that may still sync.

        Every path that queues a sync loads its rows here, so a personal
        connection whose owner can no longer sign in is left out of all of them.
        """
        stmt = (
            sa.select(IntegrationKnowledgeDBModel, UserIntegrationDBModel)
            .join(
                UserIntegrationDBModel,
                IntegrationKnowledgeDBModel.user_integration_id
                == UserIntegrationDBModel.id,
            )
            .outerjoin(Users, UserIntegrationDBModel.user_id == Users.id)
            .where(
                condition,
                sa.or_(
                    UserIntegrationDBModel.auth_type == "tenant_app",
                    owner_can_sign_in(),
                ),
            )
        )

        result = await self.session.execute(stmt)
        return result.all()  # type: ignore[return-value]

    def _is_notification_in_scope(
        self,
        notification: SharePointWebhookNotification,
        knowledge_db: IntegrationKnowledgeDBModel,
    ) -> bool:
        """Check if a webhook notification is within an integration's scope.

        For file-level integrations: notification must be for that specific file
        For folder-level integrations: notification must be in that folder/subfolders
        For site-level integrations: all notifications are in scope

        NOTE: This is a lightweight check. For folder-level integrations, we can't
        fully verify scope without metadata, so we use a heuristic: if the item
        might be related to the folder, we include it. Full scope filtering happens
        during sync service processing.

        Args:
            notification: The webhook notification
            knowledge_db: The integration knowledge record

        Returns:
            True if notification is in scope, False otherwise
        """
        # If no scope restriction (site_root), all notifications are in scope
        if not knowledge_db.folder_id and (
            knowledge_db.selected_item_type == "site_root"
            or not knowledge_db.selected_item_type
        ):
            logger.info(
                f"Knowledge {knowledge_db.id} is site-level (no folder_id, no scope); notification is in scope"
            )
            return True

        # Extract the changed item ID from notification
        resource_data = cast(dict[str, str], notification.get("resourceData") or {})
        item_id = resource_data.get("id")

        # For file-level integrations: check item_id if available, otherwise queue
        if knowledge_db.selected_item_type == "file":
            if not item_id:
                # Microsoft often doesn't send item_id in webhooks
                # Queue sync and let delta sync + sync service filtering handle it
                logger.info(
                    f"Knowledge {knowledge_db.id} is FILE-level for {knowledge_db.folder_id}; "
                    f"notification has no item_id -> QUEUEING (delta sync will check for changes)"
                )
                return True

            # If we have item_id, do exact matching
            is_in_scope = item_id == knowledge_db.folder_id
            logger.info(
                f"Knowledge {knowledge_db.id} is FILE-level for {knowledge_db.folder_id}; "
                f"notification item_id={item_id} -> {'MATCH (in scope)' if is_in_scope else 'NO MATCH (out of scope)'}"
            )
            return is_in_scope

        # For folder-level integrations: we can't fully determine scope at webhook level
        # We don't have parentReference data in the notification, so we can't verify
        # if the item is actually inside the folder.
        #
        # Strategy: Include the notification and let the sync service do the filtering.
        # The sync service has full metadata and can check parentReference properly.
        #
        # This may cause some false positives (syncing when item is outside folder),
        # but the sync service's filtering will catch those and skip them.
        # Better to have false positives (filtered later) than false negatives (missed updates).
        #
        # NOTE: Microsoft often sends notifications without item_id (just @odata.type),
        # indicating "something changed in this drive/folder". We queue these to let
        # delta sync discover what actually changed.
        if knowledge_db.selected_item_type == "folder":
            logger.info(
                f"Knowledge {knowledge_db.id} is FOLDER-level for {knowledge_db.folder_id}; "
                f"notification item_id={item_id or 'N/A'} -> QUEUEING (sync service will filter by parentReference)"
            )
            return True

        # Default: process the notification
        logger.info(
            f"Knowledge {knowledge_db.id}: Unknown selected_item_type '{knowledge_db.selected_item_type}'; "
            f"assuming in scope (fail-safe)"
        )
        return True
