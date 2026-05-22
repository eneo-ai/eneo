"""FastAPI router for the Ladan integration.

Mounted at `/api/v1/spaces` by ``server/routers.py``, but only when
:func:`feature_flag.is_enabled` returns ``True``. When the integration is
disabled the router isn't included at all — these endpoints are simply
absent rather than returning errors at request time.

Three endpoints live under ``/{id}/knowledge-sources``:
- ``POST /knowledge-sources/`` — create (needs eneo-side persistence + MCP
  registration + rollback orchestration).
- ``GET /knowledge-sources/`` — list local ownership rows (queries eneo's
  ``knowledge_sources`` table, never calls upstream).
- ``ANY /knowledge-sources/{ks_id}/upstream/{path:rest}`` — generic
  passthrough proxy for everything else (files, crawl sources, runs, ...).

The space-scoped generic MCP endpoints (POST/DELETE/GET /{id}/mcp-servers/,
refresh-tools) stay in ``spaces/api/space_router.py`` because they're not
specific to Ladan — they happen to be the substrate this integration
builds on.
"""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.ladan.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceCreateResponse,
    KnowledgeSourceSparse,
)
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

_WITH_USER = Depends(get_container(with_user=True))


async def _resolve_space_for_audit(container: Container, space_id: UUID):
    """Best-effort space lookup for the audit metadata's ``space`` field."""
    try:
        return await container.space_service().get_space(space_id)
    except Exception:
        return None


@router.post(
    "/{id}/knowledge-sources/",
    response_model=KnowledgeSourceCreateResponse,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    summary="Provision a knowledge source (plug-and-play)",
    description=(
        "Create a Ladan Collection on the user's behalf and "
        "register the paired MCP server as a space-private entry. The user "
        "only supplies a display name; eneo derives the upstream slug and "
        "uses the configured default embedding model. The resulting MCP "
        "server then appears in the assistant editor like any other."
    ),
)
async def create_space_knowledge_source(
    id: UUID,
    data: KnowledgeSourceCreate,
    container: Annotated[Container, _WITH_USER],
):
    service = container.knowledge_source_service()
    assembler = container.mcp_server_assembler()
    user = container.user()

    created = await service.create_knowledge_source(space_id=id, name=data.name)
    space = await _resolve_space_for_audit(container, id)

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.MCP_SERVER_CREATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=created.mcp_server.id,
        description=(
            f"Created knowledge source '{created.mcp_server.name}' "
            f"(Ladan slug '{created.ladan_slug}') in space "
            f"'{space.name if space else 'unknown'}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=created.mcp_server,
            space=space,
            extra={
                "space_id": str(id),
                "ladan_slug": created.ladan_slug,
                "knowledge_source_id": str(created.knowledge_source_id),
            },
        ),
    )

    return KnowledgeSourceCreateResponse(
        knowledge_source_id=created.knowledge_source_id,
        ladan_slug=created.ladan_slug,
        mcp_server=assembler.from_domain_to_model(created.mcp_server),
    )


@router.get(
    "/{id}/knowledge-sources/",
    response_model=list[KnowledgeSourceSparse],
    responses=responses.get_responses([403, 404]),
    summary="List knowledge sources owned by this space",
)
async def list_space_knowledge_sources(
    id: UUID,
    container: Annotated[Container, _WITH_USER],
):
    service = container.knowledge_source_service()
    rows = await service.list_for_space(space_id=id)
    return [
        KnowledgeSourceSparse(
            id=row.id,
            ladan_slug=row.ladan_slug,
            mcp_server_id=row.mcp_server_id,
        )
        for row in rows
    ]


_UPSTREAM_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]*$")
_AUDIT_BODY_LIMIT = 512  # bytes preserved verbatim per audit entry
_MAX_PROXY_BODY_BYTES = (
    100 * 1024 * 1024
)  # 100 MiB — accommodates typical document uploads


def _validate_upstream_path(upstream_path: str) -> str:
    """Reject path-traversal / empty / suspicious segments.

    The proxied URL is built as ``/api/collections/{slug}/{upstream_path}``.
    Disallowing ``..`` and `.` segments keeps the call scoped to one slug;
    disallowing a leading slash keeps the call inside the collection mount.
    """
    cleaned = upstream_path.strip()
    if not cleaned:
        raise BadRequestException("Upstream path may not be empty")
    if cleaned.startswith("/"):
        raise BadRequestException("Upstream path may not start with '/'")
    if not _UPSTREAM_PATH_RE.fullmatch(cleaned):
        raise BadRequestException(
            "Upstream path contains characters other than [A-Za-z0-9_-/]"
        )
    parts = cleaned.split("/")
    if any(seg in {"", ".", ".."} for seg in parts):
        raise BadRequestException("Upstream path may not contain '.' or '..' segments")
    return cleaned


def _audit_body_preview(content: bytes | None, content_type: str | None) -> str:
    """Render a body excerpt safe to drop into an audit log.

    For JSON or text content we keep the head verbatim (truncated). For
    everything else we record only the byte count, so binary uploads don't
    bloat the audit table.
    """
    if not content:
        return ""
    if content_type and (
        content_type.startswith("application/json") or content_type.startswith("text/")
    ):
        try:
            return content[:_AUDIT_BODY_LIMIT].decode("utf-8", errors="replace")
        except Exception:
            return f"<binary {len(content)} bytes>"
    return f"<{content_type or 'binary'} {len(content)} bytes>"


@router.api_route(
    "/{id}/knowledge-sources/{knowledge_source_id}/upstream/{upstream_path:path}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    responses=responses.get_responses([400, 403, 404]),
    summary="Proxy a request to the Ladan collection backing this knowledge source",
    description=(
        "Generic passthrough to `/api/collections/{slug}/{upstream_path}` on "
        "Ladan. The eneo backend authenticates the user, resolves "
        "the upstream slug from the ownership table (tenant + space gated), "
        "injects the shared admin bearer, and relays the response verbatim. "
        "Use this for any pure-passthrough operation; endpoints that need "
        "eneo-side persistence (creating a knowledge source, listing "
        "ownership rows, ...) keep their own explicit routes."
    ),
)
async def proxy_knowledge_source_request(
    id: UUID,
    knowledge_source_id: UUID,
    upstream_path: str,
    request: Request,
    container: Annotated[Container, _WITH_USER],
):
    cleaned = _validate_upstream_path(upstream_path)
    body = await request.body()
    if len(body) > _MAX_PROXY_BODY_BYTES:
        raise BadRequestException(f"Request body exceeds {_MAX_PROXY_BODY_BYTES} bytes")

    service = container.knowledge_source_service()
    user = container.user()

    ownership, proxied = await service.proxy_request(
        space_id=id,
        knowledge_source_id=knowledge_source_id,
        method=request.method,
        upstream_path=cleaned,
        body=body if body else None,
        content_type=request.headers.get("content-type"),
    )

    if request.method.upper() != "GET":
        space = await _resolve_space_for_audit(container, id)
        audit_service = container.audit_service()
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.MCP_SERVER_UPDATED,
            entity_type=EntityType.MCP_SERVER,
            entity_id=ownership.mcp_server_id,
            description=(
                f"{request.method.upper()} Ladan "
                f"'collections/{ownership.ladan_slug}/{cleaned}' "
                f"→ {proxied.status_code} in space "
                f"'{space.name if space else 'unknown'}'"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=ownership,
                space=space,
                extra={
                    "space_id": str(id),
                    "knowledge_source_id": str(knowledge_source_id),
                    "ladan_slug": ownership.ladan_slug,
                    "upstream_method": request.method.upper(),
                    "upstream_path": cleaned,
                    "upstream_status": str(proxied.status_code),
                    "request_body_preview": _audit_body_preview(
                        body, request.headers.get("content-type")
                    ),
                    "response_body_preview": _audit_body_preview(
                        proxied.content, proxied.content_type
                    ),
                },
            ),
        )

    return Response(
        content=proxied.content,
        status_code=proxied.status_code,
        media_type=proxied.content_type,
    )


# `BadRequestException` is re-exported here purely so it's discoverable from
# the package's call sites (services raise it; the router maps it to 400).
__all__ = ["router", "BadRequestException"]
