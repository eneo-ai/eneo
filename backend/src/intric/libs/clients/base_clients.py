from logging import getLogger
from types import TracebackType
from typing import Self

from intric.libs.clients.http_client import WrappedAiohttpClient

logger = getLogger(__name__)


class BaseClient:
    def __init__(self, base_url: str):
        super().__init__()
        self.client = WrappedAiohttpClient(base_url=base_url)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type:
                logger.exception(f"Exception occurred: {exc_value}")
        finally:
            await self.client.close()


class AsyncClient:
    def __init__(self, base_url: str):
        super().__init__()
        self.client = WrappedAiohttpClient(base_url=base_url)

    async def __aenter__(self) -> WrappedAiohttpClient:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type:
                logger.exception(f"Exception occurred: {exc_value}")
        finally:
            await self.client.close()
