from intric.libs.clients import SearXNGClient
from intric.main.logging import get_logger
from intric.main.models import InDB
import uuid

logger = get_logger(__name__)


class WebSearchResult(InDB):
    title: str
    url: str
    content: str
    score: float


class WebSearch:
    def __init__(self, searxng_client: SearXNGClient):
        self.searxng_client = searxng_client

    async def search(self, search_query: str, max_results: int = 10, max_search_query_length: int = 400) -> list[WebSearchResult]:
        async with self.searxng_client as client:
            response = await client.search(
                query=search_query[:max_search_query_length],
            )

            # Convert raw API response to WebSearchResult objects
            results = []
            search_results = response.get("results", [])[:max_results]

            for result in search_results:
                results.append(
                    WebSearchResult(
                        id=result.get("id", uuid.uuid4()),
                        title=result.get("title", ""),
                        url=result.get("url", ""),
                        content=result.get("content", ""),
                        score=result.get("score", 0.0),
                    )
                )

            return results
