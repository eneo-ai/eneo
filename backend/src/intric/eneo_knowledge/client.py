"""Thin HTTP client for eneo-knowledge's REST API.

Eneo holds a single ``KNOWLEDGE_API_KEY`` and proxies calls on behalf of all
tenants; tenant/space isolation is enforced inside eneo via the
``knowledge_sources`` ownership table.

Kept deliberately small — only the surface the proxied "New knowledge source"
flow needs. Other eneo-knowledge endpoints (sources, crawl runs, files)
will be added here when their flows land.
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
    """The ``mcpServer`` half of eneo-knowledge's collection-create response."""

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
class UploadedFileInfo:
    """Metadata for a file in an eneo-knowledge collection.

    ``status`` follows eneo-knowledge's lifecycle: ``queued`` ->
    ``processing`` -> ``ready`` (or ``failed`` with ``error`` populated).
    """

    id: str
    name: str
    mime_type: str
    size_bytes: int
    status: str
    error: str | None
    page_count: int | None
    created_at: str
    processed_at: str | None


class EneoKnowledgeError(BadRequestException):
    """Surface an eneo-knowledge API failure to the FastAPI layer."""


class EneoKnowledgeClient:
    """HTTP wrapper for the eneo-knowledge admin API.

    Single shared API key; tenant isolation is the caller's responsibility
    (the ``KnowledgeSourceService`` enforces it via the ownership table).
    The API key is sent as a Bearer credential per eneo-knowledge's
    current wire contract — the field name is intentionally generic on
    this side so the eneo-knowledge auth contract can evolve without a
    rename here.
    """

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = httpx.Timeout(timeout_seconds)

    async def create_collection(self, *, slug: str, name: str) -> CreatedCollection:
        """Create a collection and receive the paired ``knowledge`` MCP server.

        Returns the bearer plaintext from eneo-knowledge exactly once;
        callers must persist whatever they need (we store the URL in the
        existing ``mcp_servers`` table via the Phase 1 codepath, which
        encrypts the bearer at rest).

        eneo-knowledge picks the embedding model server-side — eneo does
        not supply one. (The model registry lives upstream; deciding which
        of several available models a new collection should use is an
        eneo-knowledge concern, not eneo's.)

        The MCP endpoint URL returned by eneo-knowledge is rewritten to share
        the origin (scheme + host + port) of our admin URL, so eneo can reach
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
            raise EneoKnowledgeError(f"Knowledge slug '{slug}' is already taken")
        if response.status_code >= 400:
            logger.warning(
                "eneo-knowledge POST /api/collections failed: %s %s",
                response.status_code,
                response.text,
            )
            raise EneoKnowledgeError(
                f"eneo-knowledge rejected collection create ({response.status_code})"
            )

        return self._parse_created_collection(response.json())

    def _rewrite_endpoint_origin(self, endpoint: str) -> str:
        """Replace the origin of an upstream-advertised URL with our admin URL's origin.

        eneo-knowledge builds MCP endpoint URLs from its own ``PUBLIC_BASE_URL``
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
                "eneo-knowledge DELETE /api/collections/%s failed: %s %s",
                slug,
                response.status_code,
                response.text,
            )
            raise EneoKnowledgeError(
                f"eneo-knowledge rejected collection delete ({response.status_code})"
            )

    async def upload_file(
        self,
        *,
        slug: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> UploadedFileInfo:
        """Upload a file to a collection. eneo-knowledge ingests asynchronously."""
        files = {"file": (filename, content, content_type)}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/collections/{slug}/files",
                files=files,
                headers=self._headers,
            )

        if response.status_code == 404:
            raise EneoKnowledgeError(
                f"Knowledge collection '{slug}' not found upstream"
            )
        if response.status_code >= 400:
            error_msg = _extract_upstream_error(response)
            logger.warning(
                "eneo-knowledge POST /api/collections/%s/files failed: %s %s",
                slug,
                response.status_code,
                response.text,
            )
            raise EneoKnowledgeError(
                error_msg
                or f"eneo-knowledge rejected file upload ({response.status_code})"
            )

        return _parse_uploaded_file(response.json())

    async def list_files(self, *, slug: str) -> list[UploadedFileInfo]:
        """List files in a collection with their ingest status."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/api/collections/{slug}/files",
                headers=self._headers,
            )

        if response.status_code == 404:
            raise EneoKnowledgeError(
                f"Knowledge collection '{slug}' not found upstream"
            )
        if response.status_code >= 400:
            logger.warning(
                "eneo-knowledge GET /api/collections/%s/files failed: %s %s",
                slug,
                response.status_code,
                response.text,
            )
            raise EneoKnowledgeError(
                f"eneo-knowledge rejected file list ({response.status_code})"
            )

        return [_parse_uploaded_file(item) for item in response.json()]

    async def delete_file(self, *, slug: str, file_id: str) -> None:
        """Delete a single file from a collection (cascades chunks + S3 object)."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.delete(
                f"{self._base_url}/api/collections/{slug}/files/{file_id}",
                headers=self._headers,
            )

        if response.status_code in (404, 200, 204):
            # 404 is treated as idempotent — the row may have been deleted
            # by an admin tool out-of-band.
            return
        if response.status_code >= 400:
            logger.warning(
                "eneo-knowledge DELETE /api/collections/%s/files/%s failed: %s %s",
                slug,
                file_id,
                response.status_code,
                response.text,
            )
            raise EneoKnowledgeError(
                f"eneo-knowledge rejected file delete ({response.status_code})"
            )


def _extract_upstream_error(response: httpx.Response) -> str | None:
    """Best-effort extraction of an ``error`` string from an upstream JSON body."""
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    body: dict[str, Any] = payload  # type: ignore[assignment]
    raw = body.get("error")
    return raw if isinstance(raw, str) else None


def _parse_uploaded_file(payload: dict[str, Any]) -> UploadedFileInfo:
    return UploadedFileInfo(
        id=payload["id"],
        name=payload["name"],
        mime_type=payload["mimeType"],
        size_bytes=payload["sizeBytes"],
        status=payload["status"],
        error=payload.get("error"),
        page_count=payload.get("pageCount"),
        created_at=payload["createdAt"],
        processed_at=payload.get("processedAt"),
    )
