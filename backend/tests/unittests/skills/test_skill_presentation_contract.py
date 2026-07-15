from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from eneo.main.exceptions import NotFoundException
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillRevision,
    SkillRevisionChange,
    SkillStatusChange,
)
from eneo.skills.presentation import skill_models, skill_router
from eneo.skills.presentation.skill_assembler import skill_binding_audit_entries
from eneo.skills.presentation.skill_router import router


def _binding(*, position: int) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        slug=f"skill-{position}",
        revision_number=position + 1,
        display_name=f"Skill {position}",
        description="Description is not audit evidence",
        instructions="Instructions are not audit evidence",
        content_digest=str(position + 1) * 64,
        position=position,
        is_active=True,
    )


def _skill(*, revision_number: int = 1, active: bool = True) -> Skill:
    skill_id = uuid4()
    revision = SkillRevision(
        id=uuid4(),
        skill_id=skill_id,
        revision_number=revision_number,
        display_name=f"Skill revision {revision_number}",
        description="Description",
        instructions="Instructions",
        content_digest=str(revision_number) * 64,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    return Skill(
        id=skill_id,
        space_id=uuid4(),
        slug="audited-skill",
        is_active=active,
        current_revision_number=revision_number,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        current_revision=revision,
    )


def _router_container(*, service, assembler):
    audit_service = SimpleNamespace(log_async=AsyncMock())
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="editor",
        email="editor@example.com",
        active_api_key=None,
    )
    container = SimpleNamespace(
        skill_service=lambda: service,
        skill_assembler=lambda: assembler,
        audit_service=lambda: audit_service,
        user=lambda: user,
    )
    return container, audit_service


def test_skill_binding_audit_entries_preserve_order_without_bodies():
    bindings = [_binding(position=0), _binding(position=1)]

    entries = skill_binding_audit_entries(bindings)

    assert [entry["skill_id"] for entry in entries] == [
        str(binding.skill_id) for binding in bindings
    ]
    assert [entry["position"] for entry in entries] == [0, 1]
    assert "instructions" not in str(entries)
    assert "description" not in str(entries)


def test_parent_binding_projection_routes_are_get_only():
    binding_paths = {
        "/spaces/{space_id}/assistants/{assistant_id}/skills/",
        "/spaces/{space_id}/apps/{app_id}/skills/",
    }
    methods_by_path = {
        route.path: route.methods
        for route in router.routes
        if isinstance(route, APIRoute) and route.path in binding_paths
    }

    assert methods_by_path == {path: {"GET"} for path in binding_paths}


def test_duplicate_binding_mutation_contracts_are_absent():
    assert not hasattr(SkillService, "create_and_attach_to_assistant")
    assert not hasattr(SkillService, "create_and_attach_to_app")
    assert not hasattr(skill_models, "SkillBindingReplaceRequest")
    assert not hasattr(skill_models, "CreateAndAttachSkillResponse")


async def test_revision_noop_result_does_not_emit_created_audit():
    skill = _skill()
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=skill),
        create_revision=AsyncMock(
            return_value=SkillRevisionChange(
                revision=skill.current_revision,
                created=False,
                previous_revision_number=skill.current_revision_number,
            )
        ),
    )
    assembler = SimpleNamespace(
        revision_to_public=MagicMock(return_value=SimpleNamespace())
    )
    container, audit_service = _router_container(service=service, assembler=assembler)

    await skill_router.create_skill_revision(
        space_id=skill.space_id,
        skill_id=skill.id,
        payload=skill_models.SkillRevisionCreateRequest(
            display_name=skill.current_revision.display_name,
            description=skill.current_revision.description,
            instructions=skill.current_revision.instructions,
        ),
        container=container,
    )

    audit_service.log_async.assert_not_awaited()


async def test_revision_created_audit_uses_locked_mutation_outcome():
    before = _skill()
    after = _skill(revision_number=2)
    after = replace(
        after,
        id=before.id,
        space_id=before.space_id,
        slug=before.slug,
        current_revision=replace(after.current_revision, skill_id=before.id),
    )
    change = SkillRevisionChange(
        revision=after.current_revision,
        created=True,
        previous_revision_number=1,
    )
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=before),
        create_revision=AsyncMock(return_value=change),
    )
    assembler = SimpleNamespace(
        revision_to_public=MagicMock(return_value=SimpleNamespace())
    )
    container, audit_service = _router_container(service=service, assembler=assembler)

    await skill_router.create_skill_revision(
        space_id=before.space_id,
        skill_id=before.id,
        payload=skill_models.SkillRevisionCreateRequest(
            display_name=after.current_revision.display_name,
            description=after.current_revision.description,
            instructions=after.current_revision.instructions,
        ),
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    changes = audit_service.log_async.await_args.kwargs["metadata"]["changes"]
    assert changes["current_revision"] == {"old": 1, "new": 2}


async def test_unchanged_status_result_does_not_emit_status_audit():
    skill = _skill(active=False)
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=skill),
        set_active=AsyncMock(
            return_value=SkillStatusChange(
                skill=skill,
                changed=False,
                previous_is_active=False,
            )
        ),
    )
    assembler = SimpleNamespace(to_public=MagicMock(return_value=SimpleNamespace()))
    container, audit_service = _router_container(service=service, assembler=assembler)

    await skill_router.set_skill_active(
        space_id=skill.space_id,
        skill_id=skill.id,
        payload=skill_models.SkillActiveUpdateRequest(is_active=False),
        container=container,
    )

    audit_service.log_async.assert_not_awaited()


async def test_delete_audit_uses_the_locked_deleted_snapshot():
    before = _skill(revision_number=1)
    deleted = _skill(revision_number=2)
    deleted = replace(
        deleted,
        id=before.id,
        space_id=before.space_id,
        slug=before.slug,
        current_revision=replace(deleted.current_revision, skill_id=before.id),
    )
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=before),
        delete_skill=AsyncMock(return_value=deleted),
    )
    container, audit_service = _router_container(
        service=service, assembler=SimpleNamespace()
    )

    await skill_router.delete_skill(
        space_id=before.space_id,
        skill_id=before.id,
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    audit_call = audit_service.log_async.await_args.kwargs
    assert "revision 2" in audit_call["description"]
    assert audit_call["metadata"]["extra"]["current_revision_number"] == 2


async def test_lost_delete_race_does_not_emit_a_second_delete_audit():
    skill = _skill()
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=skill),
        delete_skill=AsyncMock(side_effect=NotFoundException()),
    )
    container, audit_service = _router_container(
        service=service, assembler=SimpleNamespace()
    )

    with pytest.raises(NotFoundException):
        await skill_router.delete_skill(
            space_id=skill.space_id,
            skill_id=skill.id,
            container=container,
        )

    audit_service.log_async.assert_not_awaited()
