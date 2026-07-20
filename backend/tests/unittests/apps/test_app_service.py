from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.apps.apps.app_service import AppService
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.skills.domain.skill import (
    SkillBindingReference,
    SkillComposition,
    SkillExecutionReference,
)


@pytest.fixture
def service():
    skill_service = AsyncMock()
    skill_service.compose_for_app.side_effect = (
        lambda *, app_id, base_instructions: SkillComposition(
            prompt=base_instructions, provenance=()
        )
    )
    return AppService(
        user=MagicMock(),
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        factory=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        file_service=AsyncMock(),
        prompt_service=AsyncMock(),
        transcriber=AsyncMock(),
        app_template_service=AsyncMock(),
        actor_manager=MagicMock(),
        completion_service=AsyncMock(),
        icon_repo=AsyncMock(),
        skill_service=skill_service,
    )


async def test_get_raise_unauthorized_if_can_not_access(
    service: AppService,
):
    service.space_repo.get_space_by_app.return_value = MagicMock()
    actor = MagicMock()
    actor.can_read_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.get_app(MagicMock())


async def test_update_raise_unauthorized_if_can_not_edit(
    service: AppService,
):
    service.space_repo.get_space_by_app.return_value = MagicMock()
    actor = MagicMock()
    actor.can_edit_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.update_app(MagicMock())


def _configure_editable_app(service: AppService):
    app = MagicMock(id=uuid4(), space_id=uuid4())
    space = MagicMock()
    space.get_app.return_value = app
    service.space_repo.get_space_by_app.return_value = space
    actor = MagicMock()
    actor.can_edit_apps.return_value = True
    actor.get_app_permissions.return_value = []
    service.actor_manager.get_space_actor_from_space.return_value = actor
    service.repo.update.return_value = app
    return app


async def test_update_app_omitted_skills_does_not_replace_or_run_fit(
    service: AppService,
):
    app = _configure_editable_app(service)
    service._validate_configured_context = AsyncMock()  # type: ignore[method-assign]

    await service.update_app(app_id=app.id, name="Renamed")

    service.skill_service.replace_app_bindings.assert_not_awaited()
    service._validate_configured_context.assert_not_awaited()


async def test_update_app_without_skills_keeps_legacy_context_fit_behavior(
    service: AppService,
    monkeypatch,
):
    app = _configure_editable_app(service)
    service.file_service.get_files_by_ids.return_value = []
    context_assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        context_assertion,
    )

    await service.update_app(app_id=app.id, attachment_ids=[])

    context_assertion.assert_not_called()


async def test_update_app_replaces_skills_before_fit_and_parent_persist(
    service: AppService,
):
    app = _configure_editable_app(service)
    references = [
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
    ]
    events: list[str] = []

    app.update.side_effect = lambda **_: events.append("parent_update")

    async def replace_bindings(**_):
        events.append("binding_replace")

    async def validate_context(*_, **__):
        events.append("fit")

    async def persist_parent(*_, **__):
        events.append("persist")
        return app

    service.skill_service.replace_app_bindings.side_effect = replace_bindings
    service._validate_configured_context = AsyncMock(  # type: ignore[method-assign]
        side_effect=validate_context
    )
    service.repo.update.side_effect = persist_parent

    await service.update_app(
        app_id=app.id,
        skill_references=references,
    )

    service.skill_service.replace_app_bindings.assert_awaited_once_with(
        space_id=app.space_id,
        app_id=app.id,
        references=references,
    )
    assert (
        service._validate_configured_context.await_args.kwargs[
            "validate_base_without_skills"
        ]
        is True
    )
    assert events == ["parent_update", "binding_replace", "fit", "persist"]


async def test_update_app_binding_fit_failure_skips_parent_persist(
    service: AppService,
):
    app = _configure_editable_app(service)
    service._validate_configured_context = AsyncMock(  # type: ignore[method-assign]
        side_effect=BadRequestException("Composed context is too large")
    )

    with pytest.raises(BadRequestException, match="too large"):
        await service.update_app(
            app_id=app.id,
            skill_references=[],
        )

    service.skill_service.replace_app_bindings.assert_awaited_once_with(
        space_id=app.space_id,
        app_id=app.id,
        references=[],
    )
    service.repo.update.assert_not_awaited()


async def test_delete_raise_unauthorized_if_can_not_delete(
    service: AppService,
):
    service.space_repo.get_space_by_app.return_value = MagicMock()
    actor = MagicMock()
    actor.can_delete_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.delete_app(MagicMock())


async def test_publish_raise_unauthorized_has_actionable_message(
    service: AppService,
):
    space = MagicMock()
    space.get_app.return_value = MagicMock()
    service.space_repo.get_space_by_app.return_value = space

    actor = MagicMock()
    actor.can_publish_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.publish_app(MagicMock(), True)

    assert "Publishing apps" in str(exc_info.value)


@pytest.mark.parametrize("template_in_space", [True, False])
async def test_create_from_template_prefers_template_model_when_available(
    service: AppService,
    template_in_space: bool,
):
    fallback_model = MagicMock(id=uuid4())
    template_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=template_model,
        prompt_text=None,
        input_type="text-field",
        input_description="Describe input",
        name="Template",
    )
    template.validate_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    space = MagicMock()
    space.is_completion_model_in_space.return_value = template_in_space
    space.is_completion_model_available.return_value = template_in_space
    space.get_completion_model.return_value = template_model

    created_app = MagicMock(id=None, completion_model=None)
    service.app_template_service.get_app_template.return_value = template
    service.file_service.get_file_infos.return_value = []
    service.factory.create_app_from_template.return_value = created_app
    service.repo.add.return_value = created_app
    service._compose_app_prompt = AsyncMock()  # type: ignore[method-assign]

    await service._create_from_template(
        space=space,
        template_data=template_data,
        completion_model=fallback_model,
    )

    expected_model = template_model if template_in_space else fallback_model
    assert (
        service.factory.create_app_from_template.call_args.kwargs["completion_model"]
        == expected_model
    )
    service._compose_app_prompt.assert_not_awaited()


async def test_create_from_template_keeps_fallback_when_template_has_no_model(
    service: AppService,
):
    fallback_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=None,
        prompt_text=None,
        input_type="text-field",
        input_description="Describe input",
        name="Template",
    )
    template.validate_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    created_app = MagicMock(id=None, completion_model=None)
    service.app_template_service.get_app_template.return_value = template
    service.file_service.get_file_infos.return_value = []
    service.factory.create_app_from_template.return_value = created_app
    service.repo.add.return_value = created_app

    await service._create_from_template(
        space=MagicMock(),
        template_data=template_data,
        completion_model=fallback_model,
    )

    assert (
        service.factory.create_app_from_template.call_args.kwargs["completion_model"]
        == fallback_model
    )


def _execution_reference() -> SkillExecutionReference:
    return SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=2,
        content_digest="a" * 64,
        position=0,
    )


def _runnable_app():
    app = MagicMock()
    app.id = uuid4()
    app.space_id = uuid4()
    app.attachments = []
    app.completion_model = SimpleNamespace(
        name="model",
        max_input_tokens=100_000,
        vision=False,
    )
    app.get_prompt_text.return_value = "Stored base"
    app.run = AsyncMock(return_value=MagicMock())
    return app


async def test_run_app_uses_queued_skill_snapshot_instead_of_current_bindings(
    service: AppService,
):
    app = _runnable_app()
    reference = _execution_reference()
    service._get_runnable_app = AsyncMock(return_value=app)  # type: ignore[method-assign]
    service._validate_configured_context = AsyncMock()  # type: ignore[method-assign]
    service.skill_service.compose_for_execution_snapshot.return_value = (
        SkillComposition(
            prompt="Stored base\n\nQueued Skill instructions",
            provenance=(reference,),
        )
    )
    service.file_service.get_files_by_ids.return_value = []

    result = await service.run_app(
        app.id,
        file_ids=[],
        text="input",
        skill_provenance=(reference,),
    )

    service.skill_service.compose_for_execution_snapshot.assert_awaited_once_with(
        tenant_id=app.tenant_id,
        space_id=app.space_id,
        provenance=(reference,),
        base_instructions="Stored base",
    )
    service.skill_service.compose_for_app.assert_not_awaited()
    assert (
        app.run.await_args.kwargs["prompt_override"]
        == "Stored base\n\nQueued Skill instructions"
    )
    assert result.skill_provenance == (reference,)


async def test_run_app_with_no_skills_keeps_provider_prompt_override_none(
    service: AppService,
    monkeypatch,
):
    app = _runnable_app()
    service._get_runnable_app = AsyncMock(return_value=app)  # type: ignore[method-assign]
    service.file_service.get_files_by_ids.return_value = []
    context_assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        context_assertion,
    )

    result = await service.run_app(app.id, file_ids=[], text="input")

    assert app.run.await_args.kwargs["prompt_override"] is None
    assert result.skill_provenance == ()
    context_assertion.assert_not_called()


async def test_prepare_app_run_without_skills_keeps_legacy_context_fit_behavior(
    service: AppService,
    monkeypatch,
):
    app = _runnable_app()
    service._get_runnable_app = AsyncMock(return_value=app)  # type: ignore[method-assign]
    context_assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        context_assertion,
    )

    plan = await service.prepare_app_run(app.id)

    assert plan.skill_provenance == ()
    context_assertion.assert_not_called()


async def test_prepare_app_run_returns_validated_revision_snapshot(
    service: AppService,
):
    app = _runnable_app()
    reference = _execution_reference()
    service._get_runnable_app = AsyncMock(return_value=app)  # type: ignore[method-assign]
    service.skill_service.compose_for_app.side_effect = None
    service.skill_service.compose_for_app.return_value = SkillComposition(
        prompt="Stored base\n\nSkill instructions",
        provenance=(reference,),
    )
    service._validate_configured_context = AsyncMock()  # type: ignore[method-assign]

    plan = await service.prepare_app_run(app.id)

    assert plan.app is app
    assert plan.skill_provenance == (reference,)
    service._validate_configured_context.assert_awaited_once()


async def test_app_context_fit_counts_composed_prompt(service: AppService, monkeypatch):
    app = _runnable_app()
    attachment = MagicMock()
    app.attachments = [attachment]
    assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        assertion,
    )
    composition = SkillComposition(
        prompt="Base plus Skill instructions",
        provenance=(_execution_reference(),),
    )

    await service._validate_configured_context(
        app=app,
        composition=composition,
    )

    assertion.assert_called_once_with(
        max_input_tokens=app.completion_model.max_input_tokens,
        model_name=app.completion_model.name,
        prompt_text="Base plus Skill instructions",
        files=[attachment],
    )


async def test_app_binding_clear_still_checks_resulting_base_context(
    service: AppService,
    monkeypatch,
):
    app = _runnable_app()
    assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        assertion,
    )
    composition = SkillComposition(prompt="Stored base", provenance=())

    await service._validate_configured_context(
        app=app,
        composition=composition,
        validate_base_without_skills=True,
    )

    assertion.assert_called_once_with(
        max_input_tokens=app.completion_model.max_input_tokens,
        model_name=app.completion_model.name,
        prompt_text="Stored base",
        files=[],
    )


async def test_publish_app_without_skills_keeps_legacy_context_fit_behavior(
    service: AppService,
    monkeypatch,
):
    app = _runnable_app()
    space = MagicMock()
    space.get_app.return_value = app
    service.space_repo.get_space_by_app.return_value = space
    actor = MagicMock()
    actor.can_publish_apps.return_value = True
    actor.get_app_permissions.return_value = []
    service.actor_manager.get_space_actor_from_space.return_value = actor
    service.repo.update.return_value = app
    context_assertion = MagicMock()
    monkeypatch.setattr(
        "eneo.apps.apps.app_service.assert_prompt_and_files_fit_context",
        context_assertion,
    )

    await service.publish_app(app.id, True)

    context_assertion.assert_not_called()
