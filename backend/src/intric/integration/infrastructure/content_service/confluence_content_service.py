from typing import TYPE_CHECKING, cast
from uuid import UUID

import aiohttp

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.info_blobs.info_blob import InfoBlobAdd
from intric.integration.domain.entities.oauth_token import ConfluenceToken, OauthToken
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
    ) -> None:
        super().__init__()
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
        token = self._require_confluence_token(
            await self.oauth_token_repo.one(id=token_id)
        )

        async def fetch_space_content(
            token: "ConfluenceToken", start: int, space_key: str
        ) -> dict[str, object]:
            async with ConfluenceContentClient(
                base_url=token.base_url, api_token=token.access_token
            ) as content_client:
                result: dict[str, object] = await content_client.get_content(
                    start=start, space_key=space_key
                )
                return result

        size = 50
        start = 0
        while True:
            try:
                content = await fetch_space_content(
                    token=token, start=start, space_key=space_key
                )
            except aiohttp.ClientResponseError:
                token = self._require_confluence_token(
                    await self.oauth_token_service.refresh_and_update_token(
                        token_id=token.id
                    )
                )
                content = await fetch_space_content(
                    token=token, start=start, space_key=space_key
                )

            logger.info(f"Fetching knowledge, batch {start // 50}")
            raw_results = content.get("results")
            results: list[dict[str, object]] = (
                cast(list[dict[str, object]], raw_results)
                if isinstance(raw_results, list)
                else []
            )
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
        results: list[dict[str, object]],
        integration_knowledge_id: "UUID",
        token: "ConfluenceToken",
    ) -> None:
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )
        integration_knowledge_size = integration_knowledge.size
        for item in results:
            body = item.get("body")
            body_dict: dict[str, object] = (
                cast(dict[str, object], body) if isinstance(body, dict) else {}
            )
            storage = body_dict.get("storage")
            storage_dict: dict[str, object] = (
                cast(dict[str, object], storage) if isinstance(storage, dict) else {}
            )
            text = storage_dict.get("value", "")
            links = item.get("_links")
            links_dict: dict[str, object] = (
                cast(dict[str, object], links) if isinstance(links, dict) else {}
            )
            info_blob_add = InfoBlobAdd(
                title=str(item.get("title") or ""),
                user_id=self.user.id,
                text=str(text) if text else "",
                group_id=None,
                url=f"{token.base_web_url}{links_dict.get('webui', '')}",
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

    @staticmethod
    def _require_confluence_token(token: OauthToken) -> ConfluenceToken:
        if not isinstance(token, ConfluenceToken):
            raise ValueError("Expected a Confluence token")
        return token
