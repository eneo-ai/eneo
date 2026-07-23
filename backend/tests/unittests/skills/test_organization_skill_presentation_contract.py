from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.routing import APIRoute

from eneo.audit.domain.action_types import ActionType
from eneo.skills.domain.skill import (
    PublishedSkill,
    PublishedSkillSummary,
    Skill,
    SkillAdoptionDrift,
    SkillAdoptionPersonalChat,
    SkillAdoptionProjectionPage,
    SkillAdoptionResource,
    SkillAdoptionResourceKind,
    SkillAdoptionRevisionCount,
    SkillAdoptionSummary,
    SkillPublicationChange,
    SkillPublicationState,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionPage,
    SkillRevisionRestore,
    SkillRevisionSummary,
    SkillSummary,
)
from eneo.skills.presentation.organization_skill_router import (
    create_organization_skill_revision,
    get_organization_skill_adoption,
    list_organization_skill_revisions,
    publish_organization_skill,
    restore_organization_skill_revision,
    router,
)
from eneo.skills.presentation.skill_assembler import SkillAssembler
from eneo.skills.presentation.skill_models import (
    SkillPublishRequest,
    SkillRevisionCreateRequest,
    SkillRevisionPublic,
    SkillRevisionRestoreRequest,
)


def _skill(*, current_revision_number: int = 2) -> Skill:
    skill_id = uuid4()
    now = datetime.now(timezone.utc)
    revision = SkillRevision(
        id=uuid4(),
        skill_id=skill_id,
        revision_number=current_revision_number,
        display_name="Payroll",
        description="Approved payroll guidance",
        instructions="Use approved internal guidance.",
        content_digest="a" * 64,
        created_by_user_id=uuid4(),
        created_at=now,
    )
    return Skill(
        id=skill_id,
        space_id=uuid4(),
        slug="payroll",
        is_active=True,
        current_revision_number=current_revision_number,
        published_revision_number=current_revision_number,
        first_published_at=now,
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
        current_revision=revision,
    )


def test_catalogue_and_management_have_separate_read_contracts():
    paths = {
        "/skills/catalogue/",
        "/skills/catalogue/{skill_id}/",
        "/skills/organization/",
        "/skills/organization/{skill_id}/",
        "/skills/organization/{skill_id}/adoption/",
    }
    methods_by_path = {path: set() for path in paths}
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path in paths:
            methods_by_path[route.path].update(route.methods)

    assert methods_by_path == {
        "/skills/catalogue/": {"GET"},
        "/skills/catalogue/{skill_id}/": {"GET"},
        "/skills/organization/": {"GET", "POST"},
        "/skills/organization/{skill_id}/": {"GET", "DELETE"},
        "/skills/organization/{skill_id}/adoption/": {"GET"},
    }


async def test_adoption_route_projects_structural_metadata_without_skill_content():
    revision_id = uuid4()
    resource = SkillAdoptionResource(
        kind=SkillAdoptionResourceKind.ASSISTANT,
        resource_id=uuid4(),
        name="Payroll Assistant",
        space_id=uuid4(),
        space_name="People Operations",
        revision_id=revision_id,
        revision_number=1,
        drift=SkillAdoptionDrift.BEHIND,
    )
    summary = SkillAdoptionSummary(
        assistant_count=1,
        app_count=0,
        distinct_space_count=1,
        behind_published_count=2,
        personal_chat=SkillAdoptionPersonalChat(
            revision_id=revision_id,
            revision_number=1,
            drift=SkillAdoptionDrift.BEHIND,
        ),
        revision_counts=(
            SkillAdoptionRevisionCount(
                revision_id=revision_id,
                revision_number=1,
                assistant_count=1,
                app_count=0,
                personal_chat_pinned=True,
            ),
        ),
    )
    projection = SkillAdoptionProjectionPage(
        summary=summary,
        items=(resource,),
        limit=25,
        next_cursor="opaque-cursor",
    )
    service = SimpleNamespace(
        get_adoption_projection=AsyncMock(return_value=projection)
    )
    container = SimpleNamespace(
        organization_skill_service=lambda: service,
        skill_assembler=lambda: SkillAssembler(),
    )
    skill_id = uuid4()

    response = await get_organization_skill_adoption(
        skill_id=skill_id,
        limit=25,
        cursor=None,
        container=container,
    )

    service.get_adoption_projection.assert_awaited_once_with(
        skill_id=skill_id,
        limit=25,
        cursor=None,
    )
    assert response.summary is not None
    assert response.summary.assistant_count == 1
    assert response.summary.personal_chat is not None
    assert response.summary.personal_chat.revision_id == revision_id
    assert response.items[0].resource_id == resource.resource_id
    assert response.items[0].drift is SkillAdoptionDrift.BEHIND
    serialized = response.model_dump()
    assert "instructions" not in str(serialized)
    assert "content_digest" not in str(serialized)


def test_adoption_route_documents_malformed_cursor_response():
    app = FastAPI()
    app.include_router(router)

    operation = app.openapi()["paths"]["/skills/organization/{skill_id}/adoption/"][
        "get"
    ]

    assert "400" in operation["responses"]


def test_organization_revision_creation_documents_created_and_noop_responses():
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/skills/organization/{skill_id}/revisions/"
        and route.methods == {"POST"}
    )

    assert route.status_code == 201
    assert 200 in route.responses
    assert route.responses[200]["model"] is SkillRevisionPublic


def test_management_summary_exposes_status_without_instruction_bodies():
    skill = _skill()
    summary = SkillSummary(
        id=skill.id,
        space_id=skill.space_id,
        slug=skill.slug,
        is_active=skill.is_active,
        current_revision_id=skill.current_revision.id,
        current_revision_number=skill.current_revision_number,
        display_name=skill.current_revision.display_name,
        description=skill.current_revision.description,
        content_digest=skill.current_revision.content_digest,
        created_by_user_id=skill.created_by_user_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        published_revision_number=skill.published_revision_number,
        first_published_at=skill.first_published_at,
    )

    public = SkillAssembler.organization_summary_to_public(summary)

    assert public.publication_state is SkillPublicationState.PUBLISHED
    assert public.published_revision_number == 2
    assert not hasattr(public, "instructions")
    assert not hasattr(public, "current_revision")


def test_catalogue_summary_projects_the_exact_approved_revision():
    now = datetime.now(timezone.utc)
    summary = PublishedSkillSummary(
        id=uuid4(),
        slug="payroll",
        revision_id=uuid4(),
        revision_number=4,
        display_name="Payroll",
        description="Approved payroll guidance",
        content_digest="a" * 64,
        first_published_at=now,
    )

    public = SkillAssembler.published_summary_to_public(summary)

    assert public.revision_id == summary.revision_id
    assert public.revision_number == 4
    assert not hasattr(public, "instructions")


def test_catalogue_detail_exposes_approved_body_without_author_identity():
    skill = _skill()
    assert skill.first_published_at is not None
    summary = PublishedSkillSummary(
        id=skill.id,
        slug=skill.slug,
        revision_id=skill.current_revision.id,
        revision_number=skill.current_revision.revision_number,
        display_name=skill.current_revision.display_name,
        description=skill.current_revision.description,
        content_digest=skill.current_revision.content_digest,
        first_published_at=skill.first_published_at,
    )

    public = SkillAssembler.published_to_public(
        PublishedSkill(summary=summary, revision=skill.current_revision)
    )

    assert public.revision.instructions == skill.current_revision.instructions
    assert not hasattr(public.revision, "created_by_user_id")


async def test_organization_revision_history_uses_the_shared_bounded_cursor_contract():
    skill = _skill()
    summary = SkillRevisionSummary(
        id=skill.current_revision.id,
        skill_id=skill.id,
        revision_number=skill.current_revision_number,
        display_name=skill.current_revision.display_name,
        created_at=skill.current_revision.created_at,
    )
    service = SimpleNamespace(
        list_revision_summaries=AsyncMock(
            return_value=SkillRevisionPage(
                items=(summary,),
                limit=25,
                next_cursor=1,
                total_count=2,
            )
        )
    )
    container = SimpleNamespace(
        organization_skill_service=lambda: service,
        skill_assembler=lambda: SkillAssembler(),
    )

    response = await list_organization_skill_revisions(
        skill_id=skill.id,
        limit=25,
        cursor="2",
        container=container,
    )

    assert [revision.revision_number for revision in response.items] == [2]
    assert not hasattr(response.items[0], "instructions")
    assert response.limit == 25
    assert response.next_cursor == "1"
    assert response.previous_cursor is None
    assert response.total_count == 2
    service.list_revision_summaries.assert_awaited_once_with(
        skill_id=skill.id,
        limit=25,
        cursor="2",
    )


async def test_publish_audit_records_revision_identity_without_instruction_body():
    skill = _skill()
    service = SimpleNamespace(
        publish=AsyncMock(
            return_value=SkillPublicationChange(
                skill=skill,
                changed=True,
                previous_published_revision_number=None,
                previous_is_active=True,
            )
        )
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="admin",
        email="admin@example.com",
        active_api_key=None,
    )
    container = SimpleNamespace(
        organization_skill_service=lambda: service,
        skill_assembler=lambda: SkillAssembler(),
        audit_service=lambda: audit_service,
        user=lambda: user,
    )

    await publish_organization_skill(
        skill_id=skill.id,
        payload=SkillPublishRequest(
            expected_revision_id=skill.current_revision.id,
        ),
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    audit = audit_service.log_async.await_args.kwargs
    assert audit["action"] is ActionType.SKILL_PUBLISHED
    assert audit["metadata"]["changes"]["is_active"] == {
        "old": True,
        "new": True,
    }
    assert audit["metadata"]["extra"]["content_digest"] == "a" * 64
    assert "instructions" not in str(audit["metadata"])


def _revised_published_skill(before: Skill) -> Skill:
    revision = replace(
        before.current_revision,
        id=uuid4(),
        revision_number=before.current_revision_number + 1,
        content_digest="b" * 64,
    )
    return replace(
        before,
        current_revision_number=revision.revision_number,
        current_revision=revision,
    )


def _audit_container(*, service, audit_service):
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="admin",
        email="admin@example.com",
        active_api_key=None,
    )
    return SimpleNamespace(
        organization_skill_service=lambda: service,
        skill_assembler=lambda: SkillAssembler(),
        audit_service=lambda: audit_service,
        user=lambda: user,
    )


async def test_revision_created_audit_uses_persisted_post_mutation_state():
    before = _skill(current_revision_number=1)
    after = _revised_published_skill(before)
    service = SimpleNamespace(
        create_revision=AsyncMock(
            return_value=SkillRevisionChange(
                skill=after,
                revision=after.current_revision,
                created=True,
                previous_revision_number=1,
            )
        )
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())

    await create_organization_skill_revision(
        skill_id=before.id,
        payload=SkillRevisionCreateRequest(
            display_name=after.current_revision.display_name,
            description=after.current_revision.description,
            instructions=after.current_revision.instructions,
        ),
        container=_audit_container(
            service=service,
            audit_service=audit_service,
        ),
        response=Response(status_code=201),
    )

    extra = audit_service.log_async.await_args.kwargs["metadata"]["extra"]
    assert extra["current_revision_id"] == str(after.current_revision.id)
    assert extra["current_revision_number"] == 2
    assert extra["publication_state"] == SkillPublicationState.UPDATE_PENDING.value


async def test_revision_restored_audit_uses_persisted_post_mutation_state():
    before = _skill(current_revision_number=1)
    after = _revised_published_skill(before)
    service = SimpleNamespace(
        restore_revision=AsyncMock(
            return_value=SkillRevisionRestore(
                source_revision=before.current_revision,
                change=SkillRevisionChange(
                    skill=after,
                    revision=after.current_revision,
                    created=True,
                    previous_revision_number=1,
                ),
            )
        )
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())

    await restore_organization_skill_revision(
        skill_id=before.id,
        source_revision_id=before.current_revision.id,
        payload=SkillRevisionRestoreRequest(
            reviewed_current_revision_id=before.current_revision.id
        ),
        container=_audit_container(
            service=service,
            audit_service=audit_service,
        ),
    )

    service.restore_revision.assert_awaited_once_with(
        skill_id=before.id,
        source_revision_id=before.current_revision.id,
        reviewed_current_revision_id=before.current_revision.id,
    )

    extra = audit_service.log_async.await_args.kwargs["metadata"]["extra"]
    assert extra["current_revision_id"] == str(after.current_revision.id)
    assert extra["current_revision_number"] == 2
    assert extra["publication_state"] == SkillPublicationState.UPDATE_PENDING.value
