from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_session_auth
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.main.models import CursorPaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.skills.domain.skill import (
    DEFAULT_SKILL_CATALOG_PAGE_LIMIT,
    MAX_SKILL_CATALOG_PAGE_LIMIT,
    MAX_SKILL_CATALOG_QUERY_LENGTH,
    MAX_SKILL_SLUG_LENGTH,
)
from eneo.skills.presentation.skill_audit import audit_skill_created, skill_audit_extra
from eneo.skills.presentation.skill_models import (
    AssistantSkillConfigurationPublic,
    SkillActiveUpdateRequest,
    SkillBindingSummary,
    SkillCreateRequest,
    SkillPublic,
    SkillRevisionCreateRequest,
    SkillRevisionPublic,
    SkillRevisionRestorePublic,
    SkillRevisionRestoreRequest,
    SkillRevisionSummaryPublic,
    SkillSparse,
)

router = APIRouter(
    prefix="/spaces",
    tags=["skills"],
    dependencies=[Depends(require_session_auth)],
)

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]
_DEFAULT_REVISION_PAGE_LIMIT = 25
_MAX_REVISION_PAGE_LIMIT = 100


@router.get(
    "/{space_id}/skills/",
    response_model=CursorPaginatedResponse[SkillSparse],
    responses=responses.get_responses([403, 404]),
)
async def list_skills(
    space_id: UUID,
    container: _ContainerWithUser,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_SKILL_CATALOG_PAGE_LIMIT),
    ] = DEFAULT_SKILL_CATALOG_PAGE_LIMIT,
    cursor: Annotated[
        str | None,
        Query(
            max_length=MAX_SKILL_SLUG_LENGTH,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(max_length=MAX_SKILL_CATALOG_QUERY_LENGTH),
    ] = None,
) -> CursorPaginatedResponse[SkillSparse]:
    page = await container.skill_service().list_skills(
        space_id=space_id,
        limit=limit,
        cursor=cursor,
        query=q,
    )
    assembler = container.skill_assembler()
    return CursorPaginatedResponse(
        items=[assembler.catalog_entry_to_sparse(entry) for entry in page.items],
        limit=page.limit,
        next_cursor=page.next_cursor,
        previous_cursor=None,
        total_count=page.total_count,
    )


@router.post(
    "/{space_id}/skills/",
    response_model=SkillPublic,
    status_code=201,
    description="Create a Space-owned Skill with its first immutable revision.",
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def create_skill(
    space_id: UUID,
    payload: SkillCreateRequest,
    container: _ContainerWithUser,
) -> SkillPublic:
    skill = await container.skill_service().create_skill(
        space_id=space_id,
        slug=payload.slug,
        display_name=payload.display_name,
        description=payload.description,
        instructions=payload.instructions,
    )
    await audit_skill_created(container=container, skill=skill)
    return container.skill_assembler().to_public(skill)


@router.get(
    "/{space_id}/skills/{skill_id}/",
    response_model=SkillPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_skill(
    space_id: UUID,
    skill_id: UUID,
    container: _ContainerWithUser,
) -> SkillPublic:
    skill = await container.skill_service().get_skill(skill_id=skill_id)
    if skill.space_id != space_id:
        raise NotFoundException()
    return container.skill_assembler().to_public(skill)


@router.get(
    "/{space_id}/skills/{skill_id}/revisions/",
    response_model=CursorPaginatedResponse[SkillRevisionSummaryPublic],
    description="List immutable Skill revision summaries using a stable cursor.",
    responses=responses.get_responses([403, 404]),
)
async def list_skill_revisions(
    space_id: UUID,
    skill_id: UUID,
    container: _ContainerWithUser,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_REVISION_PAGE_LIMIT),
    ] = _DEFAULT_REVISION_PAGE_LIMIT,
    cursor: Annotated[str | None, Query(pattern=r"^[1-9]\d*$")] = None,
) -> CursorPaginatedResponse[SkillRevisionSummaryPublic]:
    page = await container.skill_service().list_revision_summaries(
        space_id=space_id,
        skill_id=skill_id,
        limit=limit,
        cursor=cursor,
    )
    assembler = container.skill_assembler()
    return CursorPaginatedResponse(
        items=[
            assembler.revision_summary_to_public(revision) for revision in page.items
        ],
        limit=page.limit,
        next_cursor=str(page.next_cursor) if page.next_cursor is not None else None,
        previous_cursor=None,
        total_count=page.total_count,
    )


@router.get(
    "/{space_id}/skills/{skill_id}/revisions/{revision_id}/",
    response_model=SkillRevisionPublic,
    description="Get one immutable Skill revision for review.",
    responses=responses.get_responses([403, 404]),
)
async def get_skill_revision(
    space_id: UUID,
    skill_id: UUID,
    revision_id: UUID,
    container: _ContainerWithUser,
) -> SkillRevisionPublic:
    revision = await container.skill_service().get_revision(
        space_id=space_id,
        skill_id=skill_id,
        revision_id=revision_id,
    )
    return container.skill_assembler().revision_to_public(revision)


@router.post(
    "/{space_id}/skills/{skill_id}/revisions/",
    response_model=SkillRevisionPublic,
    status_code=201,
    description=(
        "Create the next immutable Skill revision; identical current content is a "
        "no-op."
    ),
    responses={
        200: {
            "model": SkillRevisionPublic,
            "description": "The submitted content already matches the current revision.",
        },
        **responses.get_responses([400, 403, 404]),
    },
)
async def create_skill_revision(
    space_id: UUID,
    skill_id: UUID,
    payload: SkillRevisionCreateRequest,
    container: _ContainerWithUser,
    response: Response,
) -> SkillRevisionPublic:
    skill = await container.skill_service().get_skill(skill_id=skill_id)
    if skill.space_id != space_id:
        raise NotFoundException()
    change = await container.skill_service().create_revision(
        skill_id=skill_id,
        display_name=payload.display_name,
        description=payload.description,
        instructions=payload.instructions,
    )
    revision = change.revision
    if not change.created:
        response.status_code = 200
    else:
        skill = change.skill
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_REVISION_CREATED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=f"Created revision {revision.revision_number} of Skill '{revision.display_name}'",
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "current_revision": {
                        "old": change.previous_revision_number,
                        "new": revision.revision_number,
                    }
                },
                extra={
                    "slug": skill.slug,
                    "skill_revision_id": str(revision.id),
                    "content_digest": revision.content_digest,
                    "instruction_length": len(revision.instructions),
                },
            ),
        )
    return container.skill_assembler().revision_to_public(revision)


@router.post(
    "/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/",
    response_model=SkillRevisionRestorePublic,
    description=(
        "Copy an immutable historical revision into the next revision. Existing "
        "revision-pinned bindings are unchanged."
    ),
    responses=responses.get_responses([403, 404, 409]),
)
async def restore_skill_revision(
    space_id: UUID,
    skill_id: UUID,
    source_revision_id: UUID,
    payload: SkillRevisionRestoreRequest,
    container: _ContainerWithUser,
) -> SkillRevisionRestorePublic:
    outcome = await container.skill_service().restore_revision(
        space_id=space_id,
        skill_id=skill_id,
        source_revision_id=source_revision_id,
        reviewed_current_revision_id=payload.reviewed_current_revision_id,
    )
    source = outcome.source_revision
    change = outcome.change
    revision = change.revision
    if change.created:
        skill = change.skill
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_REVISION_RESTORED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=(
                f"Restored revision {source.revision_number} of Skill "
                f"'{revision.display_name}' as revision {revision.revision_number}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "current_revision": {
                        "old": change.previous_revision_number,
                        "new": revision.revision_number,
                    }
                },
                extra={
                    "slug": skill.slug,
                    "source_revision_id": str(source.id),
                    "source_revision_number": source.revision_number,
                    "restored_revision_id": str(revision.id),
                    "content_digest": revision.content_digest,
                    "instruction_length": len(revision.instructions),
                },
            ),
        )
    return SkillRevisionRestorePublic(
        revision=container.skill_assembler().revision_to_public(revision),
        created=change.created,
        restored_from_revision_id=source.id,
        restored_from_revision_number=source.revision_number,
    )


@router.patch(
    "/{space_id}/skills/{skill_id}/active/",
    response_model=SkillPublic,
    description=(
        "Activate or deactivate a Skill. Existing exact-revision bindings remain valid."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def set_skill_active(
    space_id: UUID,
    skill_id: UUID,
    payload: SkillActiveUpdateRequest,
    container: _ContainerWithUser,
) -> SkillPublic:
    skill = await container.skill_service().get_skill(skill_id=skill_id)
    if skill.space_id != space_id:
        raise NotFoundException()
    change = await container.skill_service().set_active(
        skill_id=skill_id, is_active=payload.is_active
    )
    skill = change.skill
    if change.changed:
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_STATUS_CHANGED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=f"Changed Skill '{skill.current_revision.display_name}' status",
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "is_active": {
                        "old": change.previous_is_active,
                        "new": skill.is_active,
                    }
                },
                extra=skill_audit_extra(skill),
            ),
        )
    return container.skill_assembler().to_public(skill)


@router.delete(
    "/{space_id}/skills/{skill_id}/",
    status_code=204,
    description="Delete an unbound Skill and all of its revisions.",
    responses=responses.get_responses([403, 404, 409]),
)
async def delete_skill(
    space_id: UUID, skill_id: UUID, container: _ContainerWithUser
) -> None:
    skill = await container.skill_service().get_skill(skill_id=skill_id)
    if skill.space_id != space_id:
        raise NotFoundException()
    skill = await container.skill_service().delete_skill(skill_id=skill_id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SKILL_DELETED,
        entity_type=EntityType.SKILL,
        entity_id=skill.id,
        description=f"Deleted Skill '{skill.current_revision.display_name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=skill,
            extra=skill_audit_extra(skill),
        ),
    )


@router.get(
    "/{space_id}/assistants/{assistant_id}/skills/",
    response_model=list[SkillBindingSummary],
    responses=responses.get_responses([403, 404]),
)
async def list_assistant_skill_bindings(
    space_id: UUID,
    assistant_id: UUID,
    container: _ContainerWithUser,
) -> list[SkillBindingSummary]:
    bindings = await container.skill_service().list_assistant_binding_projections(
        space_id=space_id, assistant_id=assistant_id
    )
    assembler = container.skill_assembler()
    return [assembler.binding_to_summary(binding) for binding in bindings]


@router.get(
    "/{space_id}/assistants/{assistant_id}/skills/configuration/",
    response_model=AssistantSkillConfigurationPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_assistant_skill_configuration(
    space_id: UUID,
    assistant_id: UUID,
    container: _ContainerWithUser,
) -> AssistantSkillConfigurationPublic:
    configuration = await container.assistant_service().get_skill_configuration(
        space_id=space_id,
        assistant_id=assistant_id,
    )
    return container.skill_assembler().assistant_configuration_to_public(configuration)


@router.get(
    "/{space_id}/apps/{app_id}/skills/",
    response_model=list[SkillBindingSummary],
    responses=responses.get_responses([403, 404]),
)
async def list_app_skill_bindings(
    space_id: UUID, app_id: UUID, container: _ContainerWithUser
) -> list[SkillBindingSummary]:
    bindings = await container.skill_service().list_app_binding_projections(
        space_id=space_id, app_id=app_id
    )
    assembler = container.skill_assembler()
    return [assembler.binding_to_summary(binding) for binding in bindings]
