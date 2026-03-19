from typing import TYPE_CHECKING
from uuid import UUID

import aiohttp

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.info_blobs.info_blob import InfoBlobAdd
from intric.integration.domain.entities.oauth_token import ConfluenceToken
from intric.integration.infrastructure.clients.confluence_content_client import (
    ConfluenceContentClient,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.info_blobs.info_blob_service import InfoBlobService
    from intric.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )
    from intric.jobs.job_service import JobService
    from intric.users.user import UserInDB


logger = get_logger(__name__)


class ConfluenceContentService:
    def __init__(
        self,
        job_service: "JobService",
        oauth_token_repo: "OauthTokenRepository",
        user_integration_repo: "UserIntegrationRepository",
        user: "UserInDB",
        datastore: "Datastore",
        info_blob_service: "InfoBlobService",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        oauth_token_service: "OauthTokenService",
    ):
        self.job_service = job_service
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_repo = user_integration_repo
        self.user = user
        self.datastore = datastore
        self.info_blob_service = info_blob_service
        self.integration_knowledge_repo = integration_knowledge_repo
        self.oauth_token_service = oauth_token_service

    async def pull_content(
        self,
        token_id: UUID,
        space_key: str,
        integration_knowledge_id: UUID,
    ):
        token = await self.oauth_token_repo.one(id=token_id)

        async def fetch_space_content(
            token: "ConfluenceToken", start: int, space_key: str
        ):
            async with ConfluenceContentClient(
                base_url=token.base_url, api_token=token.access_token
            ) as content_client:
                return await content_client.get_content(
                    start=start, space_key=space_key
                )

        size = 50
        start = 0
        while True:
            try:
                content = await fetch_space_content(
                    token=token, start=start, space_key=space_key
                )
            except aiohttp.ClientResponseError:
                token = await self.oauth_token_service.refresh_and_update_token(
                    token_id=token.id
                )
                content = await fetch_space_content(
                    token=token, start=start, space_key=space_key
                )

            logger.info(f"Fetching knowledge, batch {start // 50}")
            results = content.get("results")
            if results:
                await self._process_data(
                    results=results,
                    integration_knowledge_id=integration_knowledge_id,
                    token=token,
                )
                start += size
            else:
                break

    async def _process_data(
        self,
        results: list[dict],
        integration_knowledge_id: "UUID",
        token: "ConfluenceToken",
    ) -> None:
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )
        integration_knowledge_size = integration_knowledge.size
        for item in results:
            info_blob_add = InfoBlobAdd(
                title=item.get("title"),
                user_id=self.user.id,
                text=item.get("body", {}).get("storage", {}).get("value", ""),
                group_id=None,
                url=f"{token.base_web_url}{item.get('_links', {}).get('webui')}",
                website_id=None,
                tenant_id=self.user.tenant_id,
                integration_knowledge_id=integration_knowledge_id,
            )

            info_blob = await self.info_blob_service.add_info_blob_without_validation(
                info_blob_add
            )
            await self.datastore.add(
                info_blob=info_blob,
                embedding_model=integration_knowledge.embedding_model,
            )

            integration_knowledge_size += info_blob.size

        integration_knowledge.size = integration_knowledge_size
        await self.integration_knowledge_repo.update(obj=integration_knowledge)
