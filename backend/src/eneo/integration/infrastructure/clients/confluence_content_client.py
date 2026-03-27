from eneo.libs.clients import BaseClient
from eneo.main.logging import get_logger

logger = get_logger(__name__)


class ConfluenceContentClient(BaseClient):
    def __init__(self, base_url: str, api_token: str):
        super().__init__(base_url=base_url)
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def get_page(self, page_id: str, expand: str | None = None, **kwargs) -> dict:
        """
        Fetches a page's content by its ID.

        Args:
            page_id (str): The ID of the page to fetch.
            expand (str): A comma-separated list of fields to expand for detailed content.
                          Example: "body.storage,version,metadata".
        """
        params = kwargs.copy()
        if expand is None:
            params["expand"] = "body.storage"

        return await self.client.get(
            f"rest/api/content/{page_id}", headers=self.headers, params=params
        )

    async def get_content(
        self,
        expand: str | None = None,
        space_key: str | None = None,
        limit: int = 50,
        start: int = 0,
    ) -> dict:
        """
        Fetches pages content from Confluence.

        Args:
            limit (int, optional): The maximum number of pages to fetch. Default is 50.
            start (int, optional): The starting point for fetching pages. Default is 0.
            expand (str, optional): A comma-separated list of fields to expand.

        Returns:
            List of pages with optional expanded fields.
        """
        params = {"type": "page", "limit": limit, "start": start}

        if expand is None:
            params["expand"] = "body.storage"

        if space_key:
            params["spaceKey"] = space_key

        return await self.client.get(
            "rest/api/content", headers=self.headers, params=params
        )

    async def get_spaces(self, limit: int = 50, start: int = 0) -> dict:
        """Fetches spaces info from Confluence"""
        params = {"limit": limit, "start": start}
        return await self.client.get(
            "rest/api/space", headers=self.headers, params=params
        )
