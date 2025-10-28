from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import socket

from intric.integration.domain.entities.integration_knowledge import IntegrationKnowledge
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeRepository,
)
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from intric.integration.infrastructure.oauth_token_service import OauthTokenService
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


class SharePointSubscriptionService:
    def __init__(
        self,
        integration_knowledge_repo: IntegrationKnowledgeRepository,
        oauth_token_service: OauthTokenService,
    ):
        self.integration_knowledge_repo = integration_knowledge_repo
        self.oauth_token_service = oauth_token_service
        settings = get_settings()
        self.notification_url = settings.sharepoint_webhook_notification_url
        self.client_state = settings.sharepoint_webhook_client_state
        self.subscription_lifetime_minutes = settings.sharepoint_subscription_lifetime_minutes or 1440

    async def ensure_subscription(
        self,
        token: SharePointToken,
        knowledge: IntegrationKnowledge,
    ) -> IntegrationKnowledge:
        if not self.notification_url:
            logger.debug("SharePoint webhook notification URL not configured; skipping subscription")
            return knowledge

        if not knowledge.site_id:
            logger.debug("Integration knowledge %s is missing site_id; skipping subscription", knowledge.id)
            return knowledge

        expiration = datetime.now(timezone.utc) + timedelta(minutes=self.subscription_lifetime_minutes)

        drive_id = await self._resolve_drive_id(token=token, site_id=knowledge.site_id)
        if not drive_id:
            logger.warning("Could not resolve drive id for site %s; skipping subscription", knowledge.site_id)
            return knowledge

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
        }

        # Microsoft Graph only accepts the "updated" changeType for drive/root subscriptions; it also covers create/delete events.
        payload = {
            "changeType": "updated",
            "notificationUrl": self.notification_url,
            "resource": f"/sites/{knowledge.site_id}/drives/{drive_id}/root",
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
        }

        if self.client_state:
            payload["clientState"] = self.client_state

        try:
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,
                enable_cleanup_closed=True,
                force_close=True,  
                ttl_dns_cache=60,
            )

            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                trust_env=True, 
                headers={
                    "Accept": "application/json",
                    "Connection": "close",
                    "Accept-Encoding": "identity",
                },
            ) as session:
                async with session.post(
                    "https://graph.microsoft.com/v1.0/subscriptions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status >= 400:
                        try:
                            error_payload = await response.json()
                        except aiohttp.ContentTypeError:
                            error_payload = await response.text()
                        logger.error(
                            "Failed to create SharePoint subscription (status %s): %s",
                            response.status,
                            error_payload,
                        )
                        return knowledge

                    data = await response.json()

        except aiohttp.ClientError as exc:
            logger.error("Failed to create SharePoint subscription: %s", exc)
            return knowledge

        data = await response.json()
        knowledge.sharepoint_subscription_id = data.get("id")
        expires_at_str: Optional[str] = data.get("expirationDateTime")
        if expires_at_str:
            try:
                knowledge.sharepoint_subscription_expires_at = datetime.fromisoformat(
                    expires_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                logger.warning("Could not parse subscription expiration time: %s", expires_at_str)

        updated = await self.integration_knowledge_repo.update(obj=knowledge)
        logger.info(
            "Registered SharePoint subscription %s for knowledge %s",
            knowledge.sharepoint_subscription_id,
            knowledge.id,
        )
        return updated

    async def _resolve_drive_id(self, token: SharePointToken, site_id: str) -> Optional[str]:
        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as client:
            try:
                drive_id = await client.get_default_drive_id(site_id)  
                if not drive_id:
                    logger.warning("No default drive for site %s", site_id)
                return drive_id
            except Exception as exc:
                logger.error("Unable to resolve drive id for site %s: %s", site_id, exc)
                return None
            
    async def token_refresh_callback(self, token_id):
        token = await self.oauth_token_service.refresh_and_update_token(token_id=token_id)
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }
