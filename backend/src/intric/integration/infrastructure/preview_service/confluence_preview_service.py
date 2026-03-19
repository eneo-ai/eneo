from typing import TYPE_CHECKING, List

import aiohttp

from intric.integration.domain.entities.integration_preview import IntegrationPreview
from intric.integration.domain.entities.oauth_token import ConfluenceToken
from intric.integration.infrastructure.clients.confluence_content_client import (
    ConfluenceContentClient,
)
from intric.integration.infrastructure.preview_service.base_preview_service import (
    BasePreviewService,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.integration.infrastructure.oauth_token_service import OauthTokenService

logger = get_logger(__name__)


class ConfluencePreviewService(BasePreviewService):
    def __init__(self, oauth_token_service: "OauthTokenService"):
        super().__init__(oauth_token_service)

    async def get_preview_info(
        self,
        token: ConfluenceToken,
    ) -> List[IntegrationPreview]:
        async def fetch_spaces(token: ConfluenceToken):
            async with ConfluenceContentClient(
                base_url=token.base_url, api_token=token.access_token
            ) as content_client:
                return await content_client.get_spaces()

        try:
            content = await fetch_spaces(token)
        except aiohttp.ClientResponseError:
            token = await self.oauth_token_service.refresh_and_update_token(  # type: ignore[assignment]
                token_id=token.id
            )
            content = await fetch_spaces(token)

        return self._to_confluence_preview_data(content=content, token=token)

    def _to_confluence_preview_data(
        self,
        content: dict,
        token: ConfluenceToken,
    ) -> List[IntegrationPreview]:
        results = content.get("results", [])
        data: List[IntegrationPreview] = []
        for r in results:
            item = IntegrationPreview(
                name=r.get("name"),
                key=r.get("key"),
                url=self._get_confluence_url(
                    token=token, path=r.get("_links", {}).get("webui")
                ),
                type=r.get("type"),
            )
            data.append(item)
        return data

    def _get_confluence_url(self, token: ConfluenceToken, path: str) -> str:
        return f"{token.base_web_url}{path}"
