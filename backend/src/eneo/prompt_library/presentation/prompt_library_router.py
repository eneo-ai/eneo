# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse, is_provided
from eneo.prompt_library.domain.prompt_library import PromptLibraryEntry
from eneo.prompt_library.presentation.prompt_library_models import (
    PromptLibraryEntryCreate,
    PromptLibraryEntryPublic,
    PromptLibraryEntrySparse,
    PromptLibraryEntryUpdate,
    PromptLibraryVersionPublic,
)
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


def _entry_extra(entry: PromptLibraryEntry) -> dict[str, object]:
    return {
        "current_version": entry.current_version,
        "text_length": len(entry.text),
        "has_description": entry.description is not None,
    }


def _update_changes(
    before: PromptLibraryEntry, after: PromptLibraryEntry
) -> dict[str, object]:
    changes: dict[str, object] = {}
    if before.name != after.name:
        changes["name"] = {"old": before.name, "new": after.name}
    if before.description != after.description:
        changes["description_changed"] = True
    if before.text != after.text:
        changes["text"] = {
            "old_length": len(before.text),
            "new_length": len(after.text),
        }
    if before.current_version != after.current_version:
        changes["current_version"] = {
            "old": before.current_version,
            "new": after.current_version,
        }
    return changes


@router.get(
    "/",
    response_model=PaginatedResponse[PromptLibraryEntrySparse],
    responses=responses.get_responses([403]),
)
async def list_prompt_library_entries(container: _ContainerWithUser):
    service = container.prompt_library_service()
    entries = await service.list_entries()
    return PaginatedResponse(
        items=[
            container.prompt_library_assembler().to_sparse(entry) for entry in entries
        ]
    )


@router.post(
    "/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([400, 403]),
    status_code=201,
    description="Create a prompt library entry",
)
async def create_prompt_library_entry(
    payload: PromptLibraryEntryCreate,
    container: _ContainerWithUser,
):
    service = container.prompt_library_service()
    entry = await service.create_entry(
        name=payload.name,
        description=payload.description,
        text=payload.text,
    )
    assert entry.id is not None
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.PROMPT_LIBRARY_ENTRY_CREATED,
        entity_type=EntityType.PROMPT_LIBRARY_ENTRY,
        entity_id=entry.id,
        description=f"Created prompt library entry '{entry.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=entry,
            extra=_entry_extra(entry),
        ),
    )
    return container.prompt_library_assembler().to_public(entry)


@router.get(
    "/{id}/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_prompt_library_entry(id: UUID, container: _ContainerWithUser):
    service = container.prompt_library_service()
    entry = await service.get_entry(id)
    return container.prompt_library_assembler().to_public(entry)


@router.get(
    "/{id}/versions/",
    response_model=PaginatedResponse[PromptLibraryVersionPublic],
    responses=responses.get_responses([403, 404]),
)
async def list_prompt_library_entry_versions(id: UUID, container: _ContainerWithUser):
    service = container.prompt_library_service()
    versions = await service.list_versions(id)
    assembler = container.prompt_library_assembler()
    return PaginatedResponse(
        items=[assembler.version_to_public(version) for version in versions]
    )


@router.put(
    "/{id}/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([400, 403, 404]),
    description="Update a prompt library entry",
)
async def update_prompt_library_entry(
    id: UUID,
    payload: PromptLibraryEntryUpdate,
    container: _ContainerWithUser,
):
    service = container.prompt_library_service()
    before = await service.get_entry_for_update(id)
    entry = await service.update_entry(
        id,
        name=payload.name,
        description=payload.description,
        text=payload.text,
    )
    assert entry.id is not None
    changes = _update_changes(before, entry)
    if changes:
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.PROMPT_LIBRARY_ENTRY_UPDATED,
            entity_type=EntityType.PROMPT_LIBRARY_ENTRY,
            entity_id=entry.id,
            description=f"Updated prompt library entry '{entry.name}'",
            metadata=AuditMetadata.standard(
                actor=user,
                target=entry,
                changes=changes,
                extra={
                    **_entry_extra(entry),
                    "description_was_provided": is_provided(payload.description),
                },
            ),
        )
    return container.prompt_library_assembler().to_public(entry)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404, 409]),
    description="Delete a prompt library entry",
)
async def delete_prompt_library_entry(id: UUID, container: _ContainerWithUser):
    service = container.prompt_library_service()
    entry = await service.get_entry(id)
    await service.delete_entry(id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.PROMPT_LIBRARY_ENTRY_DELETED,
        entity_type=EntityType.PROMPT_LIBRARY_ENTRY,
        entity_id=id,
        description=f"Deleted prompt library entry '{entry.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=entry,
            extra=_entry_extra(entry),
        ),
    )
