from logging import getLogger

from eneo.libs.clients.http_client import WrappedAiohttpClient

logger = getLogger(__name__)


class BaseClient:
    def __init__(self, base_url: str):
        self.client = WrappedAiohttpClient(base_url=base_url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                logger.exception(f"Exception occurred: {exc_value}")
        finally:
            await self.client.close()


class AsyncClient(BaseClient):
    def __init__(self, base_url):
        super().__init__(base_url)

    async def __aenter__(self):
        return self.client
