from collections.abc import Collection, Mapping
from typing import Any

import aiohttp
from aiohttp.typedefs import Query

from intric.libs.clients.throttle_retry import (
    THROTTLE_AND_OVERLOAD_STATUS_CODES,
    THROTTLE_STATUS_CODES,
    retry_on_throttle,
)
from intric.main.exceptions import InternalHTTPException
from intric.main.logging import get_logger

logger = get_logger(__name__)

RequestHeaders = Mapping[str, str]


class WrappedAiohttpClient:
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.client = aiohttp.ClientSession()

    def _create_url(self, endpoint: str) -> str:
        return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    async def _handle_response(
        self,
        response: aiohttp.ClientResponse,
        *,
        retryable_status_codes: Collection[int] = THROTTLE_STATUS_CODES,
    ) -> Any:
        try:
            response.raise_for_status()
            return await response.json()
        except aiohttp.ClientResponseError as http_err:
            if http_err.status in retryable_status_codes:
                raise http_err
            logger.exception("HTTP error occurred:")
            raise http_err
        except aiohttp.ClientConnectionError as conn_err:
            logger.exception("Connection error occurred:")
            raise InternalHTTPException from conn_err
        except Exception as err:
            logger.exception("Unknown error:")
            raise InternalHTTPException from err

    async def get(
        self,
        endpoint: str,
        params: Query | None = None,
        headers: RequestHeaders | None = None,
    ) -> Any:
        url = self._create_url(endpoint=endpoint)

        async def _do() -> Any:
            async with self.client.get(url, params=params, headers=headers) as response:
                return await self._handle_response(
                    response,
                    retryable_status_codes=THROTTLE_AND_OVERLOAD_STATUS_CODES,
                )

        return await retry_on_throttle(
            _do,
            retryable_status_codes=THROTTLE_AND_OVERLOAD_STATUS_CODES,
        )

    async def post(
        self,
        endpoint: str,
        data: Any | None = None,
        headers: RequestHeaders | None = None,
    ) -> Any:
        url = self._create_url(endpoint=endpoint)

        async def _do() -> Any:
            async with self.client.post(url, json=data, headers=headers) as response:
                return await self._handle_response(
                    response,
                    retryable_status_codes=THROTTLE_STATUS_CODES,
                )

        return await retry_on_throttle(
            _do,
            retryable_status_codes=THROTTLE_STATUS_CODES,
        )

    async def request(
        self,
        method: str,
        endpoint: str,
        data: Any | None = None,
        params: Query | None = None,
        headers: RequestHeaders | None = None,
    ) -> Any:
        url = self._create_url(endpoint=endpoint)

        async def _do() -> Any:
            async with self.client.request(
                method, url, json=data, params=params, headers=headers
            ) as response:
                return await self._handle_response(
                    response,
                    retryable_status_codes=THROTTLE_STATUS_CODES,
                )

        return await retry_on_throttle(
            _do,
            retryable_status_codes=THROTTLE_STATUS_CODES,
        )

    async def download(
        self,
        url: str,
        headers: RequestHeaders | None = None,
    ) -> bytes:
        """Download binary content from a URL.

        Args:
            url: The full URL to download from (not appended to base_url)
            headers: Optional headers to send with the request

        Returns:
            Binary content from the response body
        """

        async def _do() -> bytes:
            try:
                async with self.client.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.read()
            except aiohttp.ClientResponseError as http_err:
                if http_err.status in THROTTLE_AND_OVERLOAD_STATUS_CODES:
                    raise http_err
                logger.exception(f"HTTP error while downloading from {url}:")
                raise http_err
            except aiohttp.ClientConnectionError as conn_err:
                logger.exception(f"Connection error while downloading from {url}:")
                raise InternalHTTPException from conn_err
            except Exception as err:
                logger.exception(f"Unknown error while downloading from {url}:")
                raise InternalHTTPException from err

        return await retry_on_throttle(
            _do,
            retryable_status_codes=THROTTLE_AND_OVERLOAD_STATUS_CODES,
        )

    async def close(self) -> None:
        if self.client and not self.client.closed:
            await self.client.close()
