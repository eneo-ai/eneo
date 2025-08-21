from typing import Any, Dict

from intric.libs.clients import BaseClient
from intric.main.logging import get_logger
from intric.main.config import SETTINGS

logger = get_logger(__name__)


class SearXNGClient(BaseClient):
    """
    Client for making API calls to SearXNG search engine.
    """

    def __init__(self):
        super().__init__(SETTINGS.searxng_base_url)

    async def search(
        self,
        query: str,
        language: str = "sv",
        pageno: int = 1,
    ) -> Dict[str, Any]:
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": pageno,
        }

        try:
            logger.debug(f"Performing SearXNG search with query: {query}")
            response = await self.client.get("search", params=params)
            logger.debug(f"SearXNG search completed, found {len(response.get('results', []))} results")
            return response

        except Exception as e:
            logger.error(f"SearXNG search failed for query '{query}': {str(e)}")
            raise
