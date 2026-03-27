import uuid

from eneo.main.config import get_settings
from eneo.main.models import InDB
from tavily import AsyncTavilyClient


class WebSearchResult(InDB):
    title: str
    url: str
    content: str
    score: float


class WebSearch:
    def __init__(self):
        self.client = AsyncTavilyClient(api_key=get_settings().tavily_api_key)

    async def search(self, search_query: str) -> list[WebSearchResult]:
        # Tavily max char limit is 400
        pruned_search_query = search_query[:400]
        response = await self.client.search(query=pruned_search_query, max_results=10)

        return [
            WebSearchResult(
                id=uuid.uuid4(),
                title=result["title"],
                url=result["url"],
                content=result["content"],
                score=result["score"],
            )
            for result in response["results"]
        ]
