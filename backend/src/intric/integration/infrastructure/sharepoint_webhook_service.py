from __future__ import annotations

from typing import Dict, List, Optional, Set
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
    UserIntegration as UserIntegrationDBModel,
)
from intric.integration.domain.repositories.oauth_token_repo import OauthTokenRepository
from intric.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from intric.integration.presentation.models import SharepointContentTaskParam
from intric.jobs.job_models import Task
from intric.jobs.job_repo import JobRepository
from intric.jobs.job_service import JobService
from intric.users.user_repo import UsersRepository
from intric.users.user import UserInDB
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


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
    ):
        self.session = session
        self.oauth_token_repo = oauth_token_repo
        self.job_repo = job_repo
        self.user_repo = user_repo
        self.change_key_service = change_key_service
        settings = get_settings()
        self.expected_client_state = settings.sharepoint_webhook_client_state

    async def handle_notifications(self, notifications: Dict) -> None:
        """Handle incoming webhook notifications from Microsoft Graph.

        ChangeKey-based deduplication prevents processing of duplicate
        notifications. Each notification item is validated before queuing.
        """
        values = notifications.get("value")
        if not values:
            logger.debug("SharePoint webhook called without notifications")
            return

        # Group notifications by site
        notifications_by_site: Dict[str, List[Dict]] = {}
        for notification in values:
            site_id = self._extract_site_id_from_notification(notification)
            if not site_id:
                continue

            if self.expected_client_state and notification.get("clientState") != self.expected_client_state:
                logger.debug("Ignoring notification with unexpected clientState")
                continue

            if site_id not in notifications_by_site:
                notifications_by_site[site_id] = []
            notifications_by_site[site_id].append(notification)

        # Process each site's notifications
        for site_id, site_notifications in notifications_by_site.items():
            await self._queue_refresh_for_site(site_id, site_notifications)

    async def _queue_refresh_for_site(
        self, site_id: str, notifications: List[Dict]
    ) -> None:
        """Queue refresh jobs for a site based on notifications.

        Validates each notification's ChangeKey before queuing to prevent
        processing duplicates. Filters integrations by scope to avoid
        unnecessary syncs for file/folder-level integrations.

        Uses site-level ChangeKey deduplication so the same webhook
        notification doesn't trigger multiple syncs.
        """
        knowledge_records = await self._fetch_knowledge_by_site(site_id=site_id)

        if not knowledge_records:
            logger.info("No integration knowledge found for SharePoint site %s", site_id)
            return

        job_services: Dict[str, JobService] = {}
        user_cache: Dict[str, UserInDB] = {}
        queued_knowledge: Set[str] = set()

        # Filter out duplicate notifications at site level first
        # This prevents the same webhook from being processed multiple times
        unique_notifications = []
        for notification in notifications:
            # Check ChangeKey at site level (not per integration)
            resource_data = notification.get("resourceData", {})
            item_id = resource_data.get("id")
            change_key = notification.get("changeKey") or resource_data.get("changeKey")

            if not item_id or not change_key:
                # Missing data - include it (fail-safe)
                unique_notifications.append(notification)
                continue

            # Check if we've already seen this item+changekey combo in this webhook batch
            # This handles the case where Microsoft sends duplicate notifications
            should_include = await self.change_key_service.should_process(
                integration_knowledge_id=site_id,  # Use site_id as integration_id for deduping
                item_id=item_id,
                change_key=change_key,
            )

            if should_include:
                unique_notifications.append(notification)
                await self.change_key_service.update_change_key(
                    integration_knowledge_id=site_id,
                    item_id=item_id,
                    change_key=change_key,
                )
                logger.info(
                    f"Site {site_id}: Notification for item {item_id} passed deduplication (new or changed)"
                )
            else:
                logger.info(
                    f"Site {site_id}: Skipping duplicate notification for item {item_id} (ChangeKey unchanged)"
                )

        if not unique_notifications:
            logger.info(f"Site {site_id}: All notifications were duplicates, nothing to sync")
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

            # Validate that user_integration_db.id is not None before proceeding
            if user_integration_db.id is None:
                logger.error(
                    "user_integration_db.id is None for knowledge %s; skipping",
                    knowledge_db.id,
                )
                continue

            # Determine authentication method and fetch appropriate credentials
            # For tenant_app integrations: use tenant_app_id, no OAuth token
            # For user_oauth integrations: use OAuth token, no tenant_app_id
            token_id: Optional[UUID] = None
            tenant_app_id: Optional[UUID] = None

            if user_integration_db.auth_type == "tenant_app":
                # Tenant app integration - no OAuth token needed
                # The worker task will fetch tenant app credentials using tenant_app_id
                tenant_app_id = user_integration_db.tenant_app_id
                if not tenant_app_id:
                    logger.warning(
                        "Tenant app integration %s has no tenant_app_id; skipping",
                        user_integration_db.id,
                    )
                    continue
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
                    continue
                token_id = token.id
                logger.info(
                    f"Using OAuth token {token_id} for integration {user_integration_db.id}"
                )

            # Determine which user to use for job creation
            # For tenant_app integrations (user_id=None), use a tenant admin
            # For user_oauth integrations, use the specific user
            if user_integration_db.user_id is None:
                # Tenant app integration - person-independent
                # Use a tenant admin for job creation
                cache_key = f"tenant_admin_{user_integration_db.tenant_id}"
                if cache_key not in user_cache:
                    try:
                        admin_user = await self._get_tenant_admin(user_integration_db.tenant_id)
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
                        continue
                user_for_job = user_cache[cache_key]
                user_id_for_job = user_for_job.id
                job_service_key = cache_key
            else:
                # User OAuth integration - use the specific user
                user_id_str = str(user_integration_db.user_id)
                if user_id_str not in user_cache:
                    try:
                        user_cache[user_id_str] = await self.user_repo.get_user_by_id(
                            id=user_integration_db.user_id
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not load user %s for SharePoint webhook notification: %s",
                            user_integration_db.user_id,
                            exc,
                        )
                        continue
                user_for_job = user_cache[user_id_str]
                user_id_for_job = user_integration_db.user_id
                job_service_key = user_id_str

            params = SharepointContentTaskParam(
                user_id=user_id_for_job,
                id=user_integration_db.id,
                token_id=token_id,  # None for tenant_app, UUID for user_oauth
                tenant_app_id=tenant_app_id,  # UUID for tenant_app, None for user_oauth
                integration_knowledge_id=knowledge_db.id,
                site_id=knowledge_db.site_id or site_id,
                folder_id=knowledge_db.folder_id,
                folder_path=knowledge_db.folder_path,
            )

            if job_service_key not in job_services:
                job_services[job_service_key] = JobService(
                    user=user_for_job,
                    job_repo=self.job_repo,
                )

            # Use delta sync if we have a delta token, otherwise do full sync
            task_type = (
                Task.SYNC_SHAREPOINT_DELTA
                if knowledge_db.delta_token
                else Task.PULL_SHAREPOINT_CONTENT
            )

            await job_services[job_service_key].queue_job(
                task=task_type,
                name=knowledge_db.name or f"SharePoint ({site_id})",
                task_params=params,
            )

            queued_knowledge.add(knowledge_id_str)
            logger.info(
                f"Queued {task_type.value} task for integration knowledge {knowledge_id_str} "
                f"(site_id={site_id})"
            )

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

        # Return the first admin (any admin will do for job creation)
        return admins[0]

    async def _fetch_knowledge_by_site(
        self, site_id: str
    ) -> List[tuple[IntegrationKnowledgeDBModel, UserIntegrationDBModel]]:
        stmt = (
            sa.select(IntegrationKnowledgeDBModel, UserIntegrationDBModel)
            .join(
                UserIntegrationDBModel,
                IntegrationKnowledgeDBModel.user_integration_id == UserIntegrationDBModel.id,
            )
            .where(IntegrationKnowledgeDBModel.site_id == site_id)
        )

        result = await self.session.execute(stmt)
        return result.all()

    def _is_notification_in_scope(
        self, notification: Dict, knowledge_db: IntegrationKnowledgeDBModel
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
        if not knowledge_db.folder_id and (knowledge_db.selected_item_type == "site_root" or not knowledge_db.selected_item_type):
            logger.info(
                f"Knowledge {knowledge_db.id} is site-level (no folder_id, no scope); notification is in scope"
            )
            return True

        # Extract the changed item ID from notification
        resource_data = notification.get("resourceData", {})
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

    async def should_process_notification(
        self,
        notification: Dict,
        knowledge_id: UUID,
    ) -> bool:
        """Validate if a webhook notification should be processed.

        Extracts ChangeKey and compares with cached value to detect
        duplicate notifications from Office.

        Args:
            notification: The webhook notification item
            knowledge_id: The integration knowledge ID

        Returns:
            True if notification should be processed, False if duplicate/no change
        """
        # Extract item ID and ChangeKey from notification
        # Format can vary by resource type (event, file, etc.)
        resource_data = notification.get("resourceData", {})
        item_id = resource_data.get("id")
        change_key = notification.get("changeKey") or resource_data.get("changeKey")

        # If either is missing, process anyway (fail-safe)
        if not item_id:
            logger.debug("No item ID in notification; processing anyway")
            return True

        if not change_key:
            logger.debug(f"No ChangeKey in notification for item {item_id}; processing anyway")
            return True

        # Check if we should process this notification
        should_process = await self.change_key_service.should_process(
            integration_knowledge_id=knowledge_id,
            item_id=item_id,
            change_key=change_key,
        )

        # If processing, update cache for next time
        if should_process:
            await self.change_key_service.update_change_key(
                integration_knowledge_id=knowledge_id,
                item_id=item_id,
                change_key=change_key,
            )

        return should_process

    def _extract_site_id_from_notification(self, notification: Dict) -> Optional[str]:
        """Extract site ID from a single notification."""
        resource: Optional[str] = notification.get("resource")
        if resource:
            site_id = self._parse_site_id(resource)
            if site_id:
                return site_id

        # Fallback: check resourceData
        site_id = notification.get("resourceData", {}).get("siteId")
        return site_id

    @staticmethod
    def _parse_site_id(resource: str) -> Optional[str]:
        # Expected formats:
        # sites/{siteId}/drives/{driveId}/root
        # sites/{siteId}/lists/{listId}
        try:
            after_sites = resource.split("sites/", 1)[1]
        except IndexError:
            return None
        site_id_part = after_sites.split("/", 1)[0]
        return site_id_part or None
