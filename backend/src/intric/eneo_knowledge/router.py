"""FastAPI router for the eneo-knowledge integration.

Mounted at `/api/v1/spaces` by ``server/routers.py``, but only when
:func:`feature_flag.is_enabled` returns ``True``. When the integration is
disabled the router isn't included at all — these endpoints are simply
absent rather than returning errors at request time.

The five endpoints all live under ``/{id}/knowledge-sources`` so they're
clearly co-located with the rest of the integration. The space-scoped
generic MCP endpoints (POST/DELETE/GET /{id}/mcp-servers/, refresh-tools)
stay in ``spaces/api/space_router.py`` because they're not specific to
eneo-knowledge — they happen to be the substrate this integration builds on.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.eneo_knowledge.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceCreateResponse,
    KnowledgeSourceFile,
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
        "Create an eneo-knowledge Collection on the user's behalf and "
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
            f"(eneo-knowledge slug '{created.eneo_knowledge_slug}') in space "
            f"'{space.name if space else 'unknown'}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=created.mcp_server,
            space=space,
            extra={
                "space_id": str(id),
                "eneo_knowledge_slug": created.eneo_knowledge_slug,
                "knowledge_source_id": str(created.knowledge_source_id),
            },
        ),
    )

    return KnowledgeSourceCreateResponse(
        knowledge_source_id=created.knowledge_source_id,
        eneo_knowledge_slug=created.eneo_knowledge_slug,
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
            eneo_knowledge_slug=row.eneo_knowledge_slug,
            mcp_server_id=row.mcp_server_id,
        )
        for row in rows
    ]


@router.get(
    "/{id}/knowledge-sources/{knowledge_source_id}/files/",
    response_model=list[KnowledgeSourceFile],
    responses=responses.get_responses([403, 404]),
    summary="List files in a knowledge source",
)
async def list_knowledge_source_files(
    id: UUID,
    knowledge_source_id: UUID,
    container: Annotated[Container, _WITH_USER],
):
    service = container.knowledge_source_service()
    files = await service.list_files(
        space_id=id, knowledge_source_id=knowledge_source_id
    )
    return [KnowledgeSourceFile.from_upstream(f) for f in files]


@router.post(
    "/{id}/knowledge-sources/{knowledge_source_id}/files/",
    response_model=KnowledgeSourceFile,
    status_code=202,
    responses=responses.get_responses([400, 403, 404]),
    summary="Upload a file to a knowledge source",
    description=(
        "Multipart upload. eneo proxies the file to eneo-knowledge which "
        "ingests asynchronously — the returned status is typically `queued`. "
        "Poll the list endpoint to follow `queued -> processing -> ready`."
    ),
)
async def upload_knowledge_source_file(
    id: UUID,
    knowledge_source_id: UUID,
    container: Annotated[Container, _WITH_USER],
    file: UploadFile = File(...),
):
    service = container.knowledge_source_service()
    user = container.user()

    content = await file.read()
    ownership, info = await service.upload_file(
        space_id=id,
        knowledge_source_id=knowledge_source_id,
        filename=file.filename or "unnamed",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )
    space = await _resolve_space_for_audit(container, id)

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=ownership.mcp_server_id,
        description=(
            f"Uploaded file '{info.name}' ({info.size_bytes} bytes) to "
            f"knowledge source slug '{ownership.eneo_knowledge_slug}' "
            f"in space '{space.name if space else 'unknown'}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=ownership,
            space=space,
            extra={
                "space_id": str(id),
                "knowledge_source_id": str(knowledge_source_id),
                "eneo_knowledge_slug": ownership.eneo_knowledge_slug,
                "file_id": info.id,
                "file_name": info.name,
                "mime_type": info.mime_type,
                "size_bytes": str(info.size_bytes),
            },
        ),
    )

    return KnowledgeSourceFile.from_upstream(info)


@router.delete(
    "/{id}/knowledge-sources/{knowledge_source_id}/files/{file_id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
    summary="Delete a file from a knowledge source",
)
async def delete_knowledge_source_file(
    id: UUID,
    knowledge_source_id: UUID,
    file_id: str,
    container: Annotated[Container, _WITH_USER],
):
    service = container.knowledge_source_service()
    user = container.user()

    ownership = await service.delete_file(
        space_id=id,
        knowledge_source_id=knowledge_source_id,
        file_id=file_id,
    )
    space = await _resolve_space_for_audit(container, id)

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=ownership.mcp_server_id,
        description=(
            f"Deleted file {file_id} from knowledge source slug "
            f"'{ownership.eneo_knowledge_slug}' in space "
            f"'{space.name if space else 'unknown'}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=ownership,
            space=space,
            extra={
                "space_id": str(id),
                "knowledge_source_id": str(knowledge_source_id),
                "eneo_knowledge_slug": ownership.eneo_knowledge_slug,
                "file_id": file_id,
            },
        ),
    )


# `BadRequestException` is re-exported here purely so it's discoverable from
# the package's call sites (services raise it; the router maps it to 400).
__all__ = ["router", "BadRequestException"]
