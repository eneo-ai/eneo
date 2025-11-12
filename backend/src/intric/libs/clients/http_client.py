from typing import Optional, Tuple

import aiohttp

from intric.main.exceptions import InternalHTTPException
from intric.main.logging import get_logger

logger = get_logger(__name__)


class WrappedAiohttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = aiohttp.ClientSession()

    def _create_url(self, endpoint: str):
        return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    async def _handle_response(self, response: aiohttp.ClientResponse):
        try:
            response.raise_for_status()
            return await response.json()
        except aiohttp.ClientResponseError as http_err:
            logger.exception("HTTP error occurred:")
            raise http_err
        except aiohttp.ClientConnectionError as conn_err:
            logger.exception("Connection error occurred:")
            raise InternalHTTPException from conn_err
        except Exception as err:
            logger.exception("Unknown error:")
            raise InternalHTTPException from err

    async def get(self, endpoint: str, params=None, headers=None):
        url = self._create_url(endpoint=endpoint)

        async with self.client.get(url, params=params, headers=headers) as response:
            return await self._handle_response(response)

    async def post(self, endpoint: str, data=None, headers=None):
        url = self._create_url(endpoint=endpoint)

        async with self.client.post(url, json=data, headers=headers) as response:
            return await self._handle_response(response)

    async def request(
        self, method: str, endpoint: str, data=None, params=None, headers=None
    ):
        url = self._create_url(endpoint=endpoint)

        async with self.client.request(
            method, url, json=data, params=params, headers=headers
        ) as response:
            return await self._handle_response(response)

    async def download(self, url: str, headers=None) -> Tuple[bytes, Optional[str]]:
        """Download binary content from a URL.

        Args:
            url: The full URL to download from (not appended to base_url)
            headers: Optional headers to send with the request

        Returns:
            Tuple containing (binary_content, content_type)
        """
        try:
            async with self.client.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.read()
        except aiohttp.ClientResponseError as http_err:
            logger.exception(f"HTTP error while downloading from {url}:")
            raise http_err
        except aiohttp.ClientConnectionError as conn_err:
            logger.exception(f"Connection error while downloading from {url}:")
            raise InternalHTTPException from conn_err
        except Exception as err:
            logger.exception(f"Unknown error while downloading from {url}:")
            raise InternalHTTPException from err

    async def close(self):
        if self.client and not self.client.closed:
            await self.client.close()
