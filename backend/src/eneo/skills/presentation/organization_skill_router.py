from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_session_auth
from eneo.main.container.container import Container
from eneo.main.models import CursorPaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.skills.domain.skill import (
    DEFAULT_SKILL_ADOPTION_PAGE_LIMIT,
    MAX_SKILL_ADOPTION_PAGE_LIMIT,
)
from eneo.skills.presentation.skill_audit import (
    audit_skill_created,
    skill_audit_extra,
)
from eneo.skills.presentation.skill_models import (
    OrganizationSkillPublic,
    OrganizationSkillSummaryPagePublic,
    PublishedSkillPublic,
    PublishedSkillSummaryPagePublic,
    SkillAdoptionProjectionPagePublic,
    SkillCreateRequest,
    SkillPublishRequest,
    SkillRevisionCreateRequest,
    SkillRevisionPublic,
    SkillRevisionRestorePublic,
    SkillRevisionRestoreRequest,
    SkillRevisionSummaryPublic,
)

router = APIRouter(
    prefix="/skills",
    tags=["skills"],
    dependencies=[Depends(require_session_auth)],
)

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]
_DEFAULT_PAGE_LIMIT = 25
_MAX_PAGE_LIMIT = 100


@router.get(
    "/catalogue/",
    response_model=PublishedSkillSummaryPagePublic,
    description="List approved Skills in the current tenant's catalogue.",
    responses=responses.get_responses([403]),
)
async def list_catalogue(
    container: _ContainerWithUser,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_LIMIT)] = _DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> PublishedSkillSummaryPagePublic:
    page = await container.organization_skill_service().list_catalogue(
        limit=limit,
        cursor=cursor,
        search=search,
    )
    assembler = container.skill_assembler()
    return PublishedSkillSummaryPagePublic(
        items=[assembler.published_summary_to_public(skill) for skill in page.items],
        limit=page.limit,
        next_cursor=page.next_cursor,
    )


@router.get(
    "/catalogue/{skill_id}/",
    response_model=PublishedSkillPublic,
    description="Open the exact approved revision of a catalogue Skill.",
    responses=responses.get_responses([403, 404]),
)
async def get_catalogue_skill(
    skill_id: UUID,
    container: _ContainerWithUser,
) -> PublishedSkillPublic:
    skill = await container.organization_skill_service().get_catalogue_skill(
        skill_id=skill_id
    )
    return container.skill_assembler().published_to_public(skill)


@router.get(
    "/organization/",
    response_model=OrganizationSkillSummaryPagePublic,
    description="List organisation Skill drafts and publication status.",
    responses=responses.get_responses([403]),
)
async def list_organization_skills(
    container: _ContainerWithUser,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_LIMIT)] = _DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> OrganizationSkillSummaryPagePublic:
    page = await container.organization_skill_service().list_organization_skills(
        limit=limit,
        cursor=cursor,
        search=search,
    )
    assembler = container.skill_assembler()
    return OrganizationSkillSummaryPagePublic(
        items=[assembler.organization_summary_to_public(skill) for skill in page.items],
        limit=page.limit,
        next_cursor=page.next_cursor,
    )


@router.post(
    "/organization/",
    response_model=OrganizationSkillPublic,
    status_code=201,
    description="Create an organisation Skill draft.",
    responses=responses.get_responses([400, 403, 409]),
)
async def create_organization_skill(
    payload: SkillCreateRequest,
    container: _ContainerWithUser,
) -> OrganizationSkillPublic:
    skill = await container.organization_skill_service().create_organization_skill(
        slug=payload.slug,
        display_name=payload.display_name,
        description=payload.description,
        instructions=payload.instructions,
    )
    await audit_skill_created(container=container, skill=skill)
    return container.skill_assembler().organization_to_public(skill)


@router.get(
    "/organization/{skill_id}/",
    response_model=OrganizationSkillPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_organization_skill(
    skill_id: UUID,
    container: _ContainerWithUser,
) -> OrganizationSkillPublic:
    skill = await container.organization_skill_service().get_organization_skill(
        skill_id=skill_id
    )
    return container.skill_assembler().organization_to_public(skill)


@router.get(
    "/organization/{skill_id}/adoption/",
    response_model=SkillAdoptionProjectionPagePublic,
    description=(
        "List structural Assistant and App adoption of an organisation Skill, "
        "with full-result revision totals."
    ),
    responses=responses.get_responses([403, 404]),
)
async def get_organization_skill_adoption(
    skill_id: UUID,
    container: _ContainerWithUser,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_SKILL_ADOPTION_PAGE_LIMIT),
    ] = DEFAULT_SKILL_ADOPTION_PAGE_LIMIT,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> SkillAdoptionProjectionPagePublic:
    projection = await container.organization_skill_service().get_adoption_projection(
        skill_id=skill_id,
        limit=limit,
        cursor=cursor,
    )
    return container.skill_assembler().adoption_projection_to_public(projection)


@router.get(
    "/organization/{skill_id}/revisions/",
    response_model=CursorPaginatedResponse[SkillRevisionSummaryPublic],
    description="List immutable revisions of an organisation Skill.",
    responses=responses.get_responses([403, 404]),
)
async def list_organization_skill_revisions(
    skill_id: UUID,
    container: _ContainerWithUser,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_LIMIT)] = _DEFAULT_PAGE_LIMIT,
    cursor: Annotated[str | None, Query(pattern=r"^[1-9]\d*$")] = None,
) -> CursorPaginatedResponse[SkillRevisionSummaryPublic]:
    page = await container.organization_skill_service().list_revision_summaries(
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
    "/organization/{skill_id}/revisions/{revision_id}/",
    response_model=SkillRevisionPublic,
    description="Open one immutable organisation Skill revision.",
    responses=responses.get_responses([403, 404]),
)
async def get_organization_skill_revision(
    skill_id: UUID,
    revision_id: UUID,
    container: _ContainerWithUser,
) -> SkillRevisionPublic:
    revision = await container.organization_skill_service().get_revision(
        skill_id=skill_id,
        revision_id=revision_id,
    )
    return container.skill_assembler().revision_to_public(revision)


@router.post(
    "/organization/{skill_id}/revisions/",
    response_model=SkillRevisionPublic,
    status_code=201,
    description=(
        "Create the next immutable organisation Skill revision; identical current "
        "content is a no-op."
    ),
    responses={
        200: {
            "model": SkillRevisionPublic,
            "description": "The submitted content already matches the current revision.",
        },
        **responses.get_responses([400, 403, 404]),
    },
)
async def create_organization_skill_revision(
    skill_id: UUID,
    payload: SkillRevisionCreateRequest,
    container: _ContainerWithUser,
    response: Response,
) -> SkillRevisionPublic:
    change = await container.organization_skill_service().create_revision(
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
            description=(
                f"Created revision {revision.revision_number} of Skill "
                f"'{revision.display_name}'"
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
                    **skill_audit_extra(skill),
                    "skill_revision_id": str(revision.id),
                    "content_digest": revision.content_digest,
                    "instruction_length": len(revision.instructions),
                },
            ),
        )
    return container.skill_assembler().revision_to_public(revision)


@router.post(
    "/organization/{skill_id}/revisions/{source_revision_id}/restore/",
    response_model=SkillRevisionRestorePublic,
    description="Restore historical content as the next immutable revision.",
    responses=responses.get_responses([403, 404, 409]),
)
async def restore_organization_skill_revision(
    skill_id: UUID,
    source_revision_id: UUID,
    payload: SkillRevisionRestoreRequest,
    container: _ContainerWithUser,
) -> SkillRevisionRestorePublic:
    outcome = await container.organization_skill_service().restore_revision(
        skill_id=skill_id,
        source_revision_id=source_revision_id,
        reviewed_current_revision_id=payload.reviewed_current_revision_id,
    )
    revision = outcome.change.revision
    if outcome.change.created:
        skill = outcome.change.skill
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_REVISION_RESTORED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=(
                f"Restored revision {outcome.source_revision.revision_number} "
                f"of Skill '{revision.display_name}' as revision "
                f"{revision.revision_number}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "current_revision": {
                        "old": outcome.change.previous_revision_number,
                        "new": revision.revision_number,
                    }
                },
                extra={
                    **skill_audit_extra(skill),
                    "skill_revision_id": str(revision.id),
                    "restored_from_revision_id": str(outcome.source_revision.id),
                    "restored_from_revision_number": (
                        outcome.source_revision.revision_number
                    ),
                    "content_digest": revision.content_digest,
                    "instruction_length": len(revision.instructions),
                },
            ),
        )
    return SkillRevisionRestorePublic(
        revision=container.skill_assembler().revision_to_public(revision),
        created=outcome.change.created,
        restored_from_revision_id=outcome.source_revision.id,
        restored_from_revision_number=outcome.source_revision.revision_number,
    )


@router.post(
    "/organization/{skill_id}/publish/",
    response_model=OrganizationSkillPublic,
    description="Publish the exact organisation Skill revision just reviewed.",
    responses=responses.get_responses([403, 404, 409]),
)
async def publish_organization_skill(
    skill_id: UUID,
    payload: SkillPublishRequest,
    container: _ContainerWithUser,
) -> OrganizationSkillPublic:
    change = await container.organization_skill_service().publish(
        skill_id=skill_id,
        expected_revision_id=payload.expected_revision_id,
    )
    if change.changed:
        skill = change.skill
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_PUBLISHED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=(
                f"Published revision {skill.published_revision_number} "
                f"of Skill '{skill.current_revision.display_name}'"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "published_revision_number": {
                        "old": change.previous_published_revision_number,
                        "new": skill.published_revision_number,
                    },
                    "is_active": {
                        "old": change.previous_is_active,
                        "new": skill.is_active,
                    },
                },
                extra=skill_audit_extra(skill),
            ),
        )
    return container.skill_assembler().organization_to_public(change.skill)


@router.post(
    "/organization/{skill_id}/unpublish/",
    response_model=OrganizationSkillPublic,
    description="Remove an organisation Skill from new catalogue use.",
    responses=responses.get_responses([403, 404]),
)
async def unpublish_organization_skill(
    skill_id: UUID,
    container: _ContainerWithUser,
) -> OrganizationSkillPublic:
    change = await container.organization_skill_service().unpublish(skill_id=skill_id)
    if change.changed:
        skill = change.skill
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.SKILL_UNPUBLISHED,
            entity_type=EntityType.SKILL,
            entity_id=skill.id,
            description=f"Unpublished Skill '{skill.current_revision.display_name}'",
            metadata=AuditMetadata.standard(
                actor=user,
                target=skill,
                changes={
                    "published_revision_number": {
                        "old": change.previous_published_revision_number,
                        "new": None,
                    },
                    "is_active": {
                        "old": change.previous_is_active,
                        "new": skill.is_active,
                    },
                },
                extra=skill_audit_extra(skill),
            ),
        )
    return container.skill_assembler().organization_to_public(change.skill)


@router.delete(
    "/organization/{skill_id}/",
    status_code=204,
    description="Delete an eligible organisation Skill draft.",
    responses=responses.get_responses([403, 404, 409]),
)
async def delete_organization_skill(
    skill_id: UUID,
    container: _ContainerWithUser,
) -> None:
    skill = await container.organization_skill_service().delete(skill_id=skill_id)
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
