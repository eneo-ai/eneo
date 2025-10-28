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
        processing duplicates.
        """
        knowledge_records = await self._fetch_knowledge_by_site(site_id=site_id)

        if not knowledge_records:
            logger.info("No integration knowledge found for SharePoint site %s", site_id)
            return

        job_services: Dict[str, JobService] = {}
        user_cache: Dict[str, UserInDB] = {}
        queued_knowledge: Set[str] = set()

        for knowledge_db, user_integration_db in knowledge_records:
            # Skip if we've already queued a job for this knowledge in this webhook
            knowledge_id_str = str(knowledge_db.id)
            if knowledge_id_str in queued_knowledge:
                logger.debug(
                    f"Skipping duplicate queue for integration knowledge {knowledge_id_str}"
                )
                continue

            # Validate at least one notification with ChangeKey should be processed
            should_process_any = False
            for notification in notifications:
                should_process = await self.should_process_notification(
                    notification=notification,
                    knowledge_id=knowledge_db.id,
                )
                if should_process:
                    should_process_any = True
                    break

            if not should_process_any:
                logger.debug(
                    f"No new changes detected for knowledge {knowledge_id_str} "
                    f"(all notifications had same or missing ChangeKey)"
                )
                continue

            token = await self.oauth_token_repo.one_or_none(
                user_integration_id=user_integration_db.id
            )
            if not token:
                logger.warning(
                    "No OAuth token found for user integration %s; skipping",
                    user_integration_db.id,
                )
                continue

            params = SharepointContentTaskParam(
                user_id=user_integration_db.user_id,
                id=user_integration_db.id,
                token_id=token.id,
                integration_knowledge_id=knowledge_db.id,
                site_id=knowledge_db.site_id or site_id,
            )

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

            if user_id_str not in job_services:
                job_services[user_id_str] = JobService(
                    user=user_cache[user_id_str],
                    job_repo=self.job_repo,
                )

            # Use delta sync if we have a delta token, otherwise do full sync
            task_type = (
                Task.SYNC_SHAREPOINT_DELTA
                if knowledge_db.delta_token
                else Task.PULL_SHAREPOINT_CONTENT
            )

            await job_services[user_id_str].queue_job(
                task=task_type,
                name=knowledge_db.name or f"SharePoint ({site_id})",
                task_params=params,
            )

            queued_knowledge.add(knowledge_id_str)
            logger.info(
                f"Queued {task_type.value} task for integration knowledge {knowledge_id_str} "
                f"(site_id={site_id})"
            )

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
