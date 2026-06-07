"""HTTP client for the generic external knowledge provider.

The provider is configured by URL + API key (see settings). Its contract, kept
deliberately permissive so different providers can satisfy it:

- ``POST /api/collections`` with ``{"name": ...}`` creates a collection and
  returns its identifiers plus an ``mcp`` block (endpoint + optional token).
- ``GET  /api/collections/{slug}/mcp`` returns the same ``mcp`` block, used when
  the create response does not inline it yet.

Nothing here is provider-specific; key aliases are accepted generously so a
provider may use camelCase or snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, cast

import httpx

_DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class ProviderCollection:
    """A collection created in the provider, with its MCP surface."""

    external_id: Optional[str]
    slug: Optional[str]
    mcp_endpoint: Optional[str]
    mcp_token: Optional[str]
    tools: list[dict[str, Any]]


class ExternalKnowledgeProviderError(Exception):
    """Raised when the provider cannot satisfy a request."""


class ExternalKnowledgeProviderClient:
    """Thin async client over the generic provider's HTTP API."""

    def __init__(self, *, base_url: str, api_key: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _request(
        self, method: str, path: str, *, json: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=_DEFAULT_TIMEOUT
        ) as client:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
            if not response.content:
                return {}
            data: Any = response.json()
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
            return {"items": data}

    @staticmethod
    def _first(data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return None

    @classmethod
    def _collection_from_response(cls, data: dict[str, Any]) -> ProviderCollection:
        mcp_raw: Any = (
            data.get("mcp") or data.get("mcpServer") or data.get("mcp_server") or {}
        )
        mcp: dict[str, Any] = (
            cast(dict[str, Any], mcp_raw) if isinstance(mcp_raw, dict) else {}
        )
        tools_raw: Any = mcp.get("tools") or data.get("tools") or []
        tools: list[dict[str, Any]] = (
            cast(list[dict[str, Any]], tools_raw) if isinstance(tools_raw, list) else []
        )
        return ProviderCollection(
            external_id=cls._first(data, "id", "collectionId", "collection_id"),
            slug=cls._first(data, "slug", "collectionSlug", "collection_slug"),
            mcp_endpoint=cls._first(mcp, "endpoint", "httpUrl", "http_url", "url"),
            mcp_token=cls._first(mcp, "token", "accessToken", "access_token"),
            tools=tools,
        )

    async def create_collection(self, *, name: str) -> ProviderCollection:
        """Create a collection and resolve its MCP endpoint (+ token)."""
        data = await self._request("POST", "/api/collections", json={"name": name})
        collection = self._collection_from_response(data)
        if collection.slug and not collection.mcp_endpoint:
            mcp = await self.get_mcp_metadata(collection_slug=collection.slug)
            collection = ProviderCollection(
                external_id=collection.external_id,
                slug=collection.slug,
                mcp_endpoint=mcp.mcp_endpoint,
                mcp_token=mcp.mcp_token,
                tools=mcp.tools,
            )
        if not collection.mcp_endpoint:
            raise ExternalKnowledgeProviderError(
                "Provider did not return an MCP endpoint for the new collection."
            )
        return collection

    async def get_mcp_metadata(self, *, collection_slug: str) -> ProviderCollection:
        data = await self._request("GET", f"/api/collections/{collection_slug}/mcp")
        return self._collection_from_response(data)


def provider_client_from_settings() -> Optional[ExternalKnowledgeProviderClient]:
    """Build a client from settings, or ``None`` when the feature is inert."""
    from intric.main.config import get_settings

    settings = get_settings()
    base_url = settings.external_knowledge_provider_url
    api_key = settings.external_knowledge_provider_api_key
    if not base_url or not api_key:
        return None
    return ExternalKnowledgeProviderClient(base_url=base_url, api_key=api_key)
