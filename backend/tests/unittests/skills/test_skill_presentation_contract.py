from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eneo.audit.domain.action_types import ActionType
from eneo.main.exceptions import NotFoundException
from eneo.main.models import NotProvided
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillActivationMode,
    SkillBindingProjection,
    SkillBindingSource,
    SkillCatalogEntry,
    SkillCatalogPage,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionPage,
    SkillRevisionRestore,
    SkillRevisionSummary,
    SkillStatusChange,
    SkillTurnEffectiveMode,
)
from eneo.skills.presentation import skill_models, skill_router
from eneo.skills.presentation.skill_assembler import (
    SkillAssembler,
    assistant_skill_binding_intents_from_input,
    skill_binding_audit_entries,
    skill_binding_references_from_input,
)
from eneo.skills.presentation.skill_models import SkillBindingReferenceInput
from eneo.skills.presentation.skill_router import router
from eneo.tokens.token_utils import TokenCountSource


def _binding(*, position: int) -> ResolvedSkillBinding:
    current_revision_id = uuid4()
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=current_revision_id,
        skill_space_id=uuid4(),
        slug=f"skill-{position}",
        revision_number=position + 1,
        current_revision_number=position + 1,
        display_name=f"Skill {position}",
        description="Description is not audit evidence",
        instructions="Instructions are not audit evidence",
        content_digest=str(position + 1) * 64,
        position=position,
        source=SkillBindingSource.SPACE,
        is_active=True,
        attachable_revision_id=current_revision_id,
        attachable_revision_number=position + 1,
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


def _summary(revision: SkillRevision) -> SkillRevisionSummary:
    return SkillRevisionSummary(
        id=revision.id,
        skill_id=revision.skill_id,
        revision_number=revision.revision_number,
        display_name=revision.display_name,
        created_at=revision.created_at,
    )


def _catalog_entry(skill: Skill) -> SkillCatalogEntry:
    revision = skill.current_revision
    return SkillCatalogEntry(
        id=skill.id,
        space_id=skill.space_id,
        slug=skill.slug,
        is_active=skill.is_active,
        current_revision_id=revision.id,
        current_revision_number=skill.current_revision_number,
        display_name=revision.display_name,
        description=revision.description,
        content_digest=revision.content_digest,
        created_by_user_id=skill.created_by_user_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
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
    bindings = [
        _binding(position=0),
        replace(
            _binding(position=1),
            activation_mode=SkillActivationMode.ON_DEMAND,
        ),
    ]

    entries = skill_binding_audit_entries(bindings)

    assert [entry["skill_id"] for entry in entries] == [
        str(binding.skill_id) for binding in bindings
    ]
    assert [entry["position"] for entry in entries] == [0, 1]
    assert [entry["activation_mode"] for entry in entries] == [
        "always",
        "on_demand",
    ]
    assert "instructions" not in str(entries)
    assert "description" not in str(entries)


def test_skill_binding_reference_input_maps_to_named_domain_reference():
    first = SkillBindingReferenceInput(skill_id=uuid4(), skill_revision_id=uuid4())
    second = SkillBindingReferenceInput(skill_id=uuid4(), skill_revision_id=uuid4())

    references = skill_binding_references_from_input([first, second])

    assert [reference.skill_id for reference in references] == [
        first.skill_id,
        second.skill_id,
    ]
    assert [reference.skill_revision_id for reference in references] == [
        first.skill_revision_id,
        second.skill_revision_id,
    ]


def test_binding_summary_carries_attachable_revision_without_catalog_lookup():
    binding = _binding(position=0)

    summary = SkillAssembler.binding_to_summary(
        SkillBindingProjection(
            binding=binding,
            execution_blocked=True,
        )
    )

    assert summary.attachable_revision_id == binding.attachable_revision_id
    assert summary.attachable_revision_number == binding.attachable_revision_number
    assert summary.source is SkillBindingSource.SPACE
    assert summary.execution_blocked is True


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


def test_revision_creation_route_documents_created_and_noop_responses():
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/spaces/{space_id}/skills/{skill_id}/revisions/"
        and route.methods == {"POST"}
    )

    assert route.status_code == 201
    assert 200 in route.responses
    assert route.responses[200]["model"] is skill_models.SkillRevisionPublic


async def test_skill_catalog_route_forwards_cursor_search_and_page_limit():
    skill = _skill()
    entry = _catalog_entry(skill)
    service = SimpleNamespace(
        list_skills=AsyncMock(
            return_value=SkillCatalogPage(
                items=(entry,),
                limit=2,
                next_cursor="audited-skill",
                total_count=3,
            )
        )
    )
    assembler = SimpleNamespace(
        catalog_entry_to_sparse=MagicMock(
            return_value=skill_models.SkillSparse(**entry.__dict__)
        )
    )
    container, _ = _router_container(service=service, assembler=assembler)

    response = await skill_router.list_skills(
        space_id=skill.space_id,
        limit=2,
        cursor="alpha-skill",
        q="  audited  ",
        container=container,
    )

    assert [item.slug for item in response.items] == ["audited-skill"]
    assert response.limit == 2
    assert response.next_cursor == "audited-skill"
    assert response.total_count == 3
    service.list_skills.assert_awaited_once_with(
        space_id=skill.space_id,
        limit=2,
        cursor="alpha-skill",
        query="  audited  ",
    )


def test_duplicate_binding_mutation_contracts_are_absent():
    assert not hasattr(SkillService, "create_and_attach_to_assistant")
    assert not hasattr(SkillService, "create_and_attach_to_app")
    assert not hasattr(SkillService, "list_revisions")
    assert not hasattr(skill_models, "SkillBindingReplaceRequest")
    assert not hasattr(skill_models, "CreateAndAttachSkillResponse")


async def test_revision_history_returns_a_bounded_body_free_cursor_page():
    skill = _skill(revision_number=3)
    revisions = (
        _summary(skill.current_revision),
        replace(
            _summary(skill.current_revision),
            id=uuid4(),
            revision_number=2,
        ),
    )
    service = SimpleNamespace(
        list_revision_summaries=AsyncMock(
            return_value=SkillRevisionPage(
                items=revisions,
                limit=2,
                next_cursor=2,
                total_count=3,
            )
        ),
    )
    assembler = SimpleNamespace(
        revision_summary_to_public=MagicMock(
            side_effect=lambda revision: skill_models.SkillRevisionSummaryPublic(
                **revision.__dict__
            )
        )
    )
    container, _ = _router_container(service=service, assembler=assembler)

    response = await skill_router.list_skill_revisions(
        space_id=skill.space_id,
        skill_id=skill.id,
        limit=2,
        cursor=None,
        container=container,
    )

    assert [revision.revision_number for revision in response.items] == [3, 2]
    assert not hasattr(response.items[0], "instructions")
    assert not hasattr(response.items[0], "description")
    assert not hasattr(response.items[0], "content_digest")
    assert not hasattr(response.items[0], "created_by_user_id")
    assert response.limit == 2
    assert response.next_cursor == "2"
    assert response.total_count == 3
    service.list_revision_summaries.assert_awaited_once_with(
        space_id=skill.space_id,
        skill_id=skill.id,
        limit=2,
        cursor=None,
    )


async def test_exact_revision_endpoint_returns_the_full_immutable_body():
    skill = _skill(revision_number=3)
    revision = replace(
        skill.current_revision,
        id=uuid4(),
        revision_number=2,
        instructions="Exact historical instructions",
    )
    service = SimpleNamespace(get_revision=AsyncMock(return_value=revision))
    assembler = SimpleNamespace(
        revision_to_public=MagicMock(
            return_value=skill_models.SkillRevisionPublic(**revision.__dict__)
        )
    )
    container, _ = _router_container(service=service, assembler=assembler)

    response = await skill_router.get_skill_revision(
        space_id=skill.space_id,
        skill_id=skill.id,
        revision_id=revision.id,
        container=container,
    )

    assert response.instructions == "Exact historical instructions"
    service.get_revision.assert_awaited_once_with(
        space_id=skill.space_id,
        skill_id=skill.id,
        revision_id=revision.id,
    )


async def test_revision_noop_result_does_not_emit_created_audit():
    skill = _skill()
    service = SimpleNamespace(
        get_skill=AsyncMock(return_value=skill),
        create_revision=AsyncMock(
            return_value=SkillRevisionChange(
                skill=skill,
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
    response = Response(status_code=201)

    await skill_router.create_skill_revision(
        space_id=skill.space_id,
        skill_id=skill.id,
        payload=skill_models.SkillRevisionCreateRequest(
            display_name=skill.current_revision.display_name,
            description=skill.current_revision.description,
            instructions=skill.current_revision.instructions,
        ),
        container=container,
        response=response,
    )

    assert response.status_code == 200
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
        skill=after,
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
    response = Response(status_code=201)

    await skill_router.create_skill_revision(
        space_id=before.space_id,
        skill_id=before.id,
        payload=skill_models.SkillRevisionCreateRequest(
            display_name=after.current_revision.display_name,
            description=after.current_revision.description,
            instructions=after.current_revision.instructions,
        ),
        container=container,
        response=response,
    )

    assert response.status_code == 201
    audit_service.log_async.assert_awaited_once()
    changes = audit_service.log_async.await_args.kwargs["metadata"]["changes"]
    assert changes["current_revision"] == {"old": 1, "new": 2}


async def test_restore_creates_a_distinct_audit_event_without_instruction_bodies():
    skill = _skill(revision_number=4)
    source = replace(
        skill.current_revision,
        id=uuid4(),
        revision_number=2,
        display_name="Earlier approved guidance",
        instructions="Historical instructions must not enter the audit log.",
        content_digest="2" * 64,
    )
    restored = replace(
        source,
        id=uuid4(),
        revision_number=5,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    outcome = SkillRevisionRestore(
        source_revision=source,
        change=SkillRevisionChange(
            skill=replace(skill, current_revision=restored, current_revision_number=5),
            revision=restored,
            created=True,
            previous_revision_number=4,
        ),
    )
    service = SimpleNamespace(restore_revision=AsyncMock(return_value=outcome))
    assembler = SimpleNamespace(
        revision_to_public=MagicMock(
            return_value=skill_models.SkillRevisionPublic(**restored.__dict__)
        )
    )
    container, audit_service = _router_container(service=service, assembler=assembler)

    response = await skill_router.restore_skill_revision(
        space_id=skill.space_id,
        skill_id=skill.id,
        source_revision_id=source.id,
        payload=skill_models.SkillRevisionRestoreRequest(
            reviewed_current_revision_id=skill.current_revision.id
        ),
        container=container,
    )

    service.restore_revision.assert_awaited_once_with(
        space_id=skill.space_id,
        skill_id=skill.id,
        source_revision_id=source.id,
        reviewed_current_revision_id=skill.current_revision.id,
    )

    assert response.created is True
    assert response.restored_from_revision_number == 2
    assert response.revision.revision_number == 5
    audit_service.log_async.assert_awaited_once()
    audit_call = audit_service.log_async.await_args.kwargs
    assert audit_call["action"] is ActionType.SKILL_REVISION_RESTORED
    assert audit_call["metadata"]["changes"]["current_revision"] == {
        "old": 4,
        "new": 5,
    }
    assert audit_call["metadata"]["extra"]["source_revision_number"] == 2
    assert "Historical instructions" not in str(audit_call["metadata"])


async def test_restore_noop_does_not_emit_a_restored_audit_event():
    skill = _skill(revision_number=4)
    outcome = SkillRevisionRestore(
        source_revision=skill.current_revision,
        change=SkillRevisionChange(
            skill=skill,
            revision=skill.current_revision,
            created=False,
            previous_revision_number=4,
        ),
    )
    service = SimpleNamespace(restore_revision=AsyncMock(return_value=outcome))
    assembler = SimpleNamespace(
        revision_to_public=MagicMock(
            return_value=skill_models.SkillRevisionPublic(
                **skill.current_revision.__dict__
            )
        )
    )
    container, audit_service = _router_container(service=service, assembler=assembler)

    response = await skill_router.restore_skill_revision(
        space_id=skill.space_id,
        skill_id=skill.id,
        source_revision_id=skill.current_revision.id,
        payload=skill_models.SkillRevisionRestoreRequest(
            reviewed_current_revision_id=skill.current_revision.id
        ),
        container=container,
    )

    assert response.created is False
    audit_service.log_async.assert_not_awaited()


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


def test_assistant_binding_input_distinguishes_omitted_and_explicit_modes():
    identity = {
        "skill_id": str(uuid4()),
        "skill_revision_id": str(uuid4()),
    }

    omitted = skill_models.AssistantSkillBindingInput.model_validate(identity)
    explicit_always = skill_models.AssistantSkillBindingInput.model_validate(
        {**identity, "activation_mode": "always"}
    )
    explicit_on_demand = skill_models.AssistantSkillBindingInput.model_validate(
        {**identity, "activation_mode": "on_demand"}
    )

    assert isinstance(omitted.activation_mode, NotProvided)
    assert "activation_mode" not in omitted.model_fields_set
    assert (
        assistant_skill_binding_intents_from_input([omitted])[0].activation_mode is None
    )
    assert explicit_always.activation_mode is SkillActivationMode.ALWAYS
    assert "activation_mode" in explicit_always.model_fields_set
    assert explicit_on_demand.activation_mode is SkillActivationMode.ON_DEMAND
    assert "activation_mode" in explicit_on_demand.model_fields_set


def test_assistant_binding_input_rejects_explicit_null_mode():
    with pytest.raises(ValidationError) as exc_info:
        skill_models.AssistantSkillBindingInput.model_validate(
            {
                "skill_id": str(uuid4()),
                "skill_revision_id": str(uuid4()),
                "activation_mode": None,
            }
        )

    assert all(
        error["loc"] and error["loc"][0] == "activation_mode"
        for error in exc_info.value.errors()
    )


def _assistant_binding_contract_app() -> FastAPI:
    app = FastAPI()

    @app.post("/binding")
    def update_binding(
        binding: skill_models.AssistantSkillBindingInput,
    ) -> dict[str, bool]:
        return {"accepted": True}

    return app


def test_assistant_binding_input_openapi_is_optional_and_non_nullable():
    schema = _assistant_binding_contract_app().openapi()["components"]["schemas"][
        "AssistantSkillBindingInput"
    ]
    activation_mode = schema["properties"]["activation_mode"]

    assert "activation_mode" not in schema.get("required", [])
    assert activation_mode["$ref"] == "#/components/schemas/SkillActivationMode"
    assert "anyOf" not in activation_mode
    assert "default" not in activation_mode


def test_assistant_binding_input_http_rejects_null_at_field():
    response = TestClient(_assistant_binding_contract_app()).post(
        "/binding",
        json={
            "skill_id": str(uuid4()),
            "skill_revision_id": str(uuid4()),
            "activation_mode": None,
        },
    )

    assert response.status_code == 422
    assert all(
        error["loc"][:2] == ["body", "activation_mode"]
        for error in response.json()["detail"]
    )


def test_shared_binding_input_rejects_assistant_activation_mode():
    with pytest.raises(ValidationError) as exc_info:
        SkillBindingReferenceInput.model_validate(
            {
                "skill_id": str(uuid4()),
                "skill_revision_id": str(uuid4()),
                "activation_mode": "on_demand",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_assistant_binding_summary_exposes_mode_without_broadening_shared_summary():
    binding = replace(
        _binding(position=0),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    projection = SkillBindingProjection(binding=binding, execution_blocked=False)

    assistant_summary = SkillAssembler.assistant_binding_to_summary(projection)
    shared_summary = SkillAssembler.binding_to_summary(projection)

    assert isinstance(assistant_summary, skill_models.AssistantSkillBindingSummary)
    assert assistant_summary.activation_mode is SkillActivationMode.ON_DEMAND
    assert "activation_mode" in assistant_summary.model_json_schema()["properties"]
    assert not hasattr(shared_summary, "activation_mode")
    assert (
        "activation_mode"
        not in skill_models.SkillBindingSummary.model_json_schema()["properties"]
    )


@pytest.mark.asyncio
async def test_assistant_skill_configuration_returns_modes_and_exact_runtime():
    binding = replace(
        _binding(position=0),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    projection = SkillBindingProjection(binding=binding, execution_blocked=False)
    model_id = uuid4()
    assistant_service = SimpleNamespace(
        get_skill_configuration=AsyncMock(
            return_value=SimpleNamespace(
                bindings=(projection,),
                runtime=SimpleNamespace(
                    effective_model_id=model_id,
                    snapshot=SimpleNamespace(
                        effective_mode=SkillTurnEffectiveMode.SELECTIVE,
                        fallback_reason=None,
                        measurement=SimpleNamespace(
                            tokens=42,
                            limit=800,
                            source=TokenCountSource.LITELLM,
                        ),
                    ),
                ),
            )
        )
    )
    container = SimpleNamespace(
        assistant_service=lambda: assistant_service,
        skill_assembler=lambda: SkillAssembler(),
    )
    space_id = uuid4()
    assistant_id = uuid4()

    response = await skill_router.get_assistant_skill_configuration(
        space_id=space_id,
        assistant_id=assistant_id,
        container=container,
    )

    assistant_service.get_skill_configuration.assert_awaited_once_with(
        space_id=space_id,
        assistant_id=assistant_id,
    )
    assert response.bindings[0].activation_mode is SkillActivationMode.ON_DEMAND
    assert response.runtime is not None
    assert response.runtime.effective_model_id == model_id
    assert response.runtime.effective_mode is SkillTurnEffectiveMode.SELECTIVE
    assert response.runtime.fallback_reason is None
    assert response.runtime.skill_context_tokens == 42
    assert response.runtime.skill_context_token_limit == 800
    assert response.runtime.token_count_source is TokenCountSource.LITELLM


def test_assistant_skill_configuration_schema_has_no_runtime_bodies():
    runtime_properties = skill_models.AssistantSkillRuntimeSummary.model_json_schema()[
        "properties"
    ]

    assert "instructions" not in runtime_properties
    assert "description" not in runtime_properties
    assert "available" not in runtime_properties
    assert "active" not in runtime_properties
    assert "accepted" not in runtime_properties


def test_assistant_skill_configuration_route_is_get_only():
    methods = {
        method
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path
        == "/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/"
        for method in route.methods
    }

    assert methods == {"GET"}
