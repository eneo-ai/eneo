from typing import TYPE_CHECKING, List, cast

import aiohttp
from typing_extensions import override

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import ConfluenceToken, OauthToken
from eneo.integration.infrastructure.clients.confluence_content_client import (
    ConfluenceContentClient,
)
from eneo.integration.infrastructure.preview_service.base_preview_service import (
    BasePreviewService,
)
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.integration.infrastructure.oauth_token_service import OauthTokenService

logger = get_logger(__name__)


class ConfluencePreviewService(BasePreviewService):
    def __init__(self, oauth_token_service: "OauthTokenService"):
        super().__init__(oauth_token_service)

    @override
    async def get_preview_info(
        self,
        token: OauthToken,
    ) -> List[IntegrationPreview]:
        confluence_token = self._require_confluence_token(token)

        async def fetch_spaces(token: ConfluenceToken) -> dict[str, object]:
            async with ConfluenceContentClient(
                base_url=token.base_url, api_token=token.access_token
            ) as content_client:
                result: dict[str, object] = await content_client.get_spaces()
                return result

        try:
            content = await fetch_spaces(confluence_token)
        except aiohttp.ClientResponseError:
            refreshed_token = await self.oauth_token_service.refresh_and_update_token(
                token_id=confluence_token.id
            )
            confluence_token = self._require_confluence_token(refreshed_token)
            content = await fetch_spaces(confluence_token)

        return self._to_confluence_preview_data(content=content, token=confluence_token)

    @staticmethod
    def _require_confluence_token(token: OauthToken) -> ConfluenceToken:
        if not isinstance(token, ConfluenceToken):
            raise ValueError("Expected a Confluence token")
        return token

    def _to_confluence_preview_data(
        self,
        content: dict[str, object],
        token: ConfluenceToken,
    ) -> List[IntegrationPreview]:
        raw_results = content.get("results", [])
        results: list[dict[str, object]] = (
            cast(list[dict[str, object]], raw_results)
            if isinstance(raw_results, list)
            else []
        )
        data: List[IntegrationPreview] = []
        for r in results:
            links = r.get("_links")
            links_dict: dict[str, object] = (
                cast(dict[str, object], links) if isinstance(links, dict) else {}
            )
            webui = links_dict.get("webui", "")
            item = IntegrationPreview(
                name=str(r.get("name") or ""),
                key=str(r.get("key") or ""),
                url=self._get_confluence_url(token=token, path=str(webui)),
                type=str(r.get("type") or ""),
            )
            data.append(item)
        return data

    def _get_confluence_url(self, token: ConfluenceToken, path: str) -> str:
        return f"{token.base_web_url}{path}"
