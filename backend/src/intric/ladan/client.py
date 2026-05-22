"""Thin HTTP client for Ladan's REST API.

Eneo holds a single ``LADAN_API_KEY`` and proxies calls on behalf of all
tenants; tenant/space isolation is enforced inside eneo via the
``knowledge_sources`` ownership table.

Three operations live here as explicit methods because they participate in
eneo-side state changes (collection create/delete) or are the generic
passthrough used by everything else: ``create_collection``,
``delete_collection``, ``proxy_collection_request``. All other Ladan
endpoints (files, crawl sources, runs, ...) are reached via the proxy
mount in ``router.py`` — no per-operation method needed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from intric.main.exceptions import BadRequestException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairedMcpServer:
    """The ``mcpServer`` half of Ladan's collection-create response."""

    id: str
    slug: str
    name: str
    endpoint: str
    bearer: str
    template_id: str | None


@dataclass(frozen=True)
class KnowledgeCollection:
    """The ``collection`` half of the response."""

    id: str
    slug: str
    name: str
    embedding_model_id: str


@dataclass(frozen=True)
class CreatedCollection:
    collection: KnowledgeCollection
    mcp_server: PairedMcpServer


@dataclass(frozen=True)
class ProxiedResponse:
    """Raw upstream response payload, forwarded by the generic proxy mount.

    The eneo router relays ``status_code``, ``content`` (bytes), and
    ``content_type`` verbatim to the eneo user — no schema validation, no
    body translation. Ladan is the source of truth for the wire contract
    under ``/api/collections/{slug}/**``.
    """

    status_code: int
    content: bytes
    content_type: str | None


class LadanError(BadRequestException):
    """Surface a Ladan API failure to the FastAPI layer."""


class LadanClient:
    """HTTP wrapper for the Ladan admin API.

    Single shared API key; tenant isolation is the caller's responsibility
    (the ``KnowledgeSourceService`` enforces it via the ownership table).
    The API key is sent as a Bearer credential per Ladan's current wire
    contract — the field name is intentionally generic on this side so
    Ladan's auth contract can evolve without a rename here.
    """

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = httpx.Timeout(timeout_seconds)

    async def create_collection(self, *, slug: str, name: str) -> CreatedCollection:
        """Create a collection and receive the paired ``knowledge`` MCP server.

        Returns the bearer plaintext from Ladan exactly once; callers
        must persist whatever they need (we store the URL in the existing
        ``mcp_servers`` table via the Phase 1 codepath, which encrypts
        the bearer at rest).

        Ladan picks the embedding model server-side — eneo does not
        supply one. (The model registry lives upstream; deciding which
        of several available models a new collection should use is a
        Ladan concern, not eneo's.)

        The MCP endpoint URL returned by Ladan is rewritten to share the
        origin (scheme + host + port) of our admin URL, so eneo can reach
        the MCP runtime over the same network path it just used for the
        admin call. See ``_rewrite_endpoint_origin``.
        """
        body = {"slug": slug, "name": name}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/collections",
                json=body,
                headers=self._headers,
            )

        if response.status_code == 409:
            raise LadanError(f"Knowledge slug '{slug}' is already taken")
        if response.status_code >= 400:
            logger.warning(
                "Ladan POST /api/collections failed: %s %s",
                response.status_code,
                response.text,
            )
            raise LadanError(
                f"Ladan rejected collection create ({response.status_code})"
            )

        return self._parse_created_collection(response.json())

    def _rewrite_endpoint_origin(self, endpoint: str) -> str:
        """Replace the origin of an upstream-advertised URL with our admin URL's origin.

        Ladan builds MCP endpoint URLs from its own ``PUBLIC_BASE_URL``
        (typically ``http://localhost:3001`` in dev), which is unreachable from
        inside eneo's devcontainer. We already know an origin that DOES reach
        the same instance — the admin URL we just used — so we swap it in,
        keeping the path/slug intact.
        """
        try:
            upstream = urlparse(endpoint)
            admin = urlparse(self._base_url)
        except ValueError:
            return endpoint
        if not admin.scheme or not admin.netloc:
            return endpoint
        return urlunparse(upstream._replace(scheme=admin.scheme, netloc=admin.netloc))

    def _parse_created_collection(self, payload: dict[str, Any]) -> CreatedCollection:
        collection_data = payload["collection"]
        mcp_data = payload["mcpServer"]
        return CreatedCollection(
            collection=KnowledgeCollection(
                id=collection_data["id"],
                slug=collection_data["slug"],
                name=collection_data["name"],
                embedding_model_id=collection_data["embeddingModelId"],
            ),
            mcp_server=PairedMcpServer(
                id=mcp_data["id"],
                slug=mcp_data["slug"],
                name=mcp_data["name"],
                endpoint=self._rewrite_endpoint_origin(mcp_data["mcpEndpoint"]),
                bearer=mcp_data["mcpBearerToken"],
                template_id=mcp_data.get("templateId"),
            ),
        )

    async def delete_collection(self, *, slug: str) -> None:
        """Delete a collection by slug. Cascades to the paired MCP server."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.delete(
                f"{self._base_url}/api/collections/{slug}",
                headers=self._headers,
            )

        if response.status_code in (404, 200, 204):
            # 404 is acceptable (already deleted upstream) — surfaced as
            # idempotent so eneo can recover from out-of-band cleanup.
            return
        if response.status_code >= 400:
            logger.warning(
                "Ladan DELETE /api/collections/%s failed: %s %s",
                slug,
                response.status_code,
                response.text,
            )
            raise LadanError(
                f"Ladan rejected collection delete ({response.status_code})"
            )

    async def proxy_collection_request(
        self,
        *,
        slug: str,
        method: str,
        upstream_path: str,
        body: bytes | None,
        content_type: str | None,
    ) -> "ProxiedResponse":
        """Forward an arbitrary request to /api/collections/{slug}/{upstream_path}.

        Used by the generic Ladan proxy mount: the caller already
        validated the upstream path and resolved tenant + space ownership.
        The admin bearer is injected here; the response is returned verbatim
        for the FastAPI handler to relay to the eneo user.
        """
        headers = dict(self._headers)
        if content_type:
            headers["Content-Type"] = content_type
        url = f"{self._base_url}/api/collections/{slug}/{upstream_path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                method.upper(),
                url,
                content=body,
                headers=headers,
            )
        return ProxiedResponse(
            status_code=response.status_code,
            content=response.content,
            content_type=response.headers.get("content-type"),
        )
