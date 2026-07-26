from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.assistants.assistant_service import AssistantService
from eneo.files.attachment_budget import attachment_token_ceiling
from eneo.files.file_models import FileType
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    SkillActivationMode,
    SkillBindingProjection,
    SkillBindingSource,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
    SkillTurnEffectiveMode,
    SkillTurnPlan,
)
from eneo.tokens.token_utils import TokenCountSource


def _settings(**overrides):
    base = dict(
        attachment_max_files=100,
        attachment_max_size_bytes=26214400,
        attachment_context_reserve_tokens=2000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_reserve(monkeypatch, reserve):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: _settings(attachment_context_reserve_tokens=reserve),
    )


def _text_attachment():
    return MagicMock(file_type=FileType.TEXT, mimetype="text/plain", size=1)


def _image_attachment():
    return MagicMock(file_type=FileType.IMAGE)


def _service(file_service=None):
    skill_service = AsyncMock()
    skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        SkillRuntimeResolution(eligible=(), blocked=())
    )
    skill_service.create_turn_plan.side_effect = (
        lambda *, base_instructions, resolution: SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=10,
                max_activations_per_turn=3,
            ),
        )
    )
    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        user=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=file_service or AsyncMock(),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(),
        actor_manager=MagicMock(),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=AsyncMock(),
        help_assistant_assignment_history_repo=AsyncMock(),
        skill_service=skill_service,
    )
    return service


def _domain_assistant():
    return Assistant(
        id=None,
        user=MagicMock(),
        name=MagicMock(),
        space_id=MagicMock(),
        prompt=None,
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=False,
    )


def _assistant_with(max_input_tokens, n_attachments=1, prompt_text=None, vision=False):
    model = SimpleNamespace(
        max_input_tokens=max_input_tokens,
        name="gpt-4o",
        vision=vision,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/gpt-4o",
    )
    prompt = SimpleNamespace(text=prompt_text) if prompt_text is not None else None
    return SimpleNamespace(
        id=None,
        is_default=False,
        completion_model=model,
        attachments=[_text_attachment() for _ in range(n_attachments)],
        prompt=prompt,
        get_prompt_text=lambda: prompt_text or "",
    )


def _resolved_skill(
    *,
    name: str,
    position: int,
    activation_mode: SkillActivationMode,
) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug=name.lower(),
        revision_number=1,
        current_revision_number=1,
        display_name=name,
        description=f"Use {name} when relevant",
        instructions=f"Instructions for {name}",
        content_digest="a" * 64,
        position=position,
        source=SkillBindingSource.SPACE,
        activation_mode=activation_mode,
    )


def _assistant_with_runtime_model(*, prompt_text: str = "Base instructions"):
    model = SimpleNamespace(
        id=uuid4(),
        max_input_tokens=16_000,
        name="gpt-4o",
        vision=False,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/gpt-4o",
    )
    return SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        is_default=False,
        completion_model=model,
        attachments=[],
        prompt=SimpleNamespace(text=prompt_text),
        get_prompt_text=lambda: prompt_text,
    )


# --- fit ceiling (single source of truth) ---


def test_attachment_token_ceiling_subtracts_reserve(monkeypatch):
    _patch_reserve(monkeypatch, 2000)
    assert attachment_token_ceiling(100_000) == 98_000
    # Reserve larger than the window floors at 0 rather than going negative.
    _patch_reserve(monkeypatch, 200_000)
    assert attachment_token_ceiling(8_000) == 0


# --- count cap (domain, abuse guardrail) ---


def test_validate_attachments_raises_above_count_cap(monkeypatch):
    monkeypatch.setattr(
        "eneo.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    with pytest.raises(BadRequestException):
        Assistant.validate_attachments([_text_attachment() for _ in range(4)])


def test_validate_attachments_passes_at_count_cap(monkeypatch):
    monkeypatch.setattr(
        "eneo.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    Assistant.validate_attachments([_text_attachment() for _ in range(3)])


def test_validate_attachments_rejects_non_text_mimetype(monkeypatch):
    monkeypatch.setattr(
        "eneo.assistants.assistant.get_settings",
        lambda: _settings(),
    )
    with pytest.raises(BadRequestException, match="text files"):
        Assistant.validate_attachments(
            [MagicMock(mimetype="image/png", size=1, file_type=FileType.IMAGE)]
        )


def test_validate_attachments_rejects_total_size_above_cap(monkeypatch):
    monkeypatch.setattr(
        "eneo.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_size_bytes=10),
    )
    with pytest.raises(BadRequestException, match="maximum total size"):
        Assistant.validate_attachments(
            [
                MagicMock(mimetype="text/plain", size=6, file_type=FileType.TEXT),
                MagicMock(mimetype="text/plain", size=5, file_type=FileType.TEXT),
            ]
        )


def test_update_enforces_count_cap_through_setter(monkeypatch):
    # The service update path routes attachments through Assistant.update -> the
    # setter, so the cap is enforced server-side on update, not just in the
    # static validator.
    monkeypatch.setattr(
        "eneo.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=2),
    )
    assistant = _domain_assistant()
    files = [
        MagicMock(mimetype="text/plain", size=1, file_type=FileType.TEXT)
        for _ in range(3)
    ]
    with pytest.raises(BadRequestException):
        assistant.update(attachments=files)


# --- context fit (service, always on): prompt + attachments must fit ---


@pytest.mark.asyncio
async def test_fit_rejects_when_over_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 5)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **k: 90,
    )
    # ceiling = 100 - 10 = 90; used = prompt 5 + attachments 90 = 95 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service()._validate_attachments_fit(
            _assistant_with(100, prompt_text="x"), space=MagicMock()
        )


@pytest.mark.asyncio
async def test_fit_passes_when_within(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 5)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **k: 80,
    )
    # used = 85 <= ceiling 90 -> ok
    await _service()._validate_attachments_fit(
        _assistant_with(100, prompt_text="x"), space=MagicMock()
    )


@pytest.mark.asyncio
async def test_fit_passes_at_exact_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **k: 90,
    )
    # used == ceiling is allowed (block only when strictly over)
    await _service()._validate_attachments_fit(_assistant_with(100), space=MagicMock())


@pytest.mark.asyncio
async def test_fit_skipped_when_no_model(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **k: 10**9,
    )
    assistant = SimpleNamespace(
        id=None,
        is_default=False,
        completion_model=None,
        attachments=[_text_attachment()],
        prompt=None,
        get_prompt_text=lambda: "",
    )
    await _service()._validate_attachments_fit(assistant, space=MagicMock())  # no raise


@pytest.mark.asyncio
async def test_fit_counts_derived_images_for_vision_model(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)

    def fake_count_attachment_tokens(*, text_files, image_files, model_name):
        return len(text_files) * 10 + len(image_files) * 90

    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        fake_count_attachment_tokens,
    )
    text_attachment = _text_attachment()
    derived_image = _image_attachment()
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[text_attachment, derived_image]
    )

    # ceiling = 100 - 10 = 90; text 10 + derived image 90 = 100 -> reject
    with pytest.raises(BadRequestException):
        await _service(file_service)._validate_attachments_fit(
            _assistant_with(100, vision=True), space=MagicMock()
        )

    file_service.with_derived_images.assert_awaited_once()


@pytest.mark.asyncio
async def test_fit_does_not_count_derived_images_without_vision(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)

    def fake_count_attachment_tokens(*, text_files, image_files, model_name):
        return len(text_files) * 10 + len(image_files) * 90

    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        fake_count_attachment_tokens,
    )
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[_text_attachment(), _image_attachment()]
    )

    await _service(file_service)._validate_attachments_fit(
        _assistant_with(100), space=MagicMock()
    )

    file_service.with_derived_images.assert_not_awaited()


# --- context fit: the prompt counts on its own, even with no attachments ---


@pytest.mark.asyncio
async def test_fit_rejects_prompt_only_over_ceiling(monkeypatch):
    # A system prompt that alone overflows must be rejected even with zero
    # attachments — the ceiling covers prompt + attachments, not attachments
    # alone (regression guard: the early-return on empty attachments hid this).
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 95)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens", lambda **k: 0
    )
    assistant = _assistant_with(100, n_attachments=0, prompt_text="huge prompt")
    # ceiling = 90; prompt 95 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service()._validate_attachments_fit(assistant, space=MagicMock())


@pytest.mark.asyncio
async def test_fit_passes_prompt_only_within_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 50)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens", lambda **k: 0
    )
    assistant = _assistant_with(100, n_attachments=0, prompt_text="ok prompt")
    # ceiling = 90; prompt 50 <= 90 -> ok
    await _service()._validate_attachments_fit(assistant, space=MagicMock())


@pytest.mark.parametrize(
    ("bindings", "selective_activation_enabled"),
    [
        ((), True),
        (
            (
                _resolved_skill(
                    name="Always",
                    position=0,
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
            ),
            True,
        ),
        (
            (
                _resolved_skill(
                    name="Always",
                    position=0,
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
                _resolved_skill(
                    name="On demand",
                    position=1,
                    activation_mode=SkillActivationMode.ON_DEMAND,
                ),
            ),
            True,
        ),
        (
            (
                _resolved_skill(
                    name="Always",
                    position=0,
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
                _resolved_skill(
                    name="On demand",
                    position=1,
                    activation_mode=SkillActivationMode.ON_DEMAND,
                ),
            ),
            False,
        ),
    ],
    ids=("none", "all-always", "mixed-selective", "mixed-disabled"),
)
async def test_save_fit_uses_the_exact_initial_turn_runtime_prompt(
    bindings: tuple[ResolvedSkillBinding, ...],
    selective_activation_enabled: bool,
    monkeypatch,
):
    """Save must validate the exact prompt ask() creates, not eagerly compose
    every attached Skill through a parallel calculation."""

    measurement = SimpleNamespace(
        tokens=10,
        limit=1_000,
        source=TokenCountSource.LITELLM,
    )
    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        lambda **_: measurement,
    )
    policy = SkillRuntimePolicy(
        selective_activation_enabled=selective_activation_enabled,
        max_attached_skills=100,
        context_share_percent=10,
        max_activations_per_turn=3,
    )
    resolution = SkillRuntimeResolution(eligible=bindings, blocked=())
    assistant = _assistant_with_runtime_model()
    space = MagicMock()
    space.is_personal.return_value = False
    service = _service()
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        resolution
    )
    service.skill_service.create_turn_plan.side_effect = (
        lambda *, base_instructions, resolution: SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=policy,
        )
    )
    service._assert_persistent_baseline_fits = AsyncMock()

    expected_plan = SkillTurnPlan.create(
        base_instructions=assistant.get_prompt_text(),
        resolution=resolution,
        policy=policy,
    )
    expected_runtime = expected_plan.to_activation_runtime(
        selected_model_route=assistant.completion_model.get_model_route(),
        max_input_tokens=assistant.completion_model.max_input_tokens,
        supports_tool_calling=assistant.completion_model.supports_tool_calling,
    )

    await service._validate_attachments_fit(assistant, space=space)

    assert (
        service._assert_persistent_baseline_fits.await_args.kwargs["prompt_text"]
        == expected_runtime.prompt
    )
    service.skill_service.create_turn_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_preflight_baseline_uses_the_exact_initial_turn_runtime_prompt(
    monkeypatch,
):
    bindings = (
        _resolved_skill(
            name="Always",
            position=0,
            activation_mode=SkillActivationMode.ALWAYS,
        ),
        _resolved_skill(
            name="On demand",
            position=1,
            activation_mode=SkillActivationMode.ON_DEMAND,
        ),
    )
    measurement = SimpleNamespace(
        tokens=10,
        limit=1_000,
        source=TokenCountSource.LITELLM,
    )
    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        lambda **_: measurement,
    )
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=10,
        max_activations_per_turn=3,
    )
    resolution = SkillRuntimeResolution(eligible=bindings, blocked=())
    assistant = _assistant_with_runtime_model()
    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.is_personal.return_value = False
    service = _service()
    service.space_repo.get_space_by_assistant.return_value = space
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        resolution
    )
    service.skill_service.create_turn_plan.side_effect = (
        lambda *, base_instructions, resolution: SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=policy,
        )
    )

    expected_runtime = SkillTurnPlan.create(
        base_instructions=assistant.get_prompt_text(),
        resolution=resolution,
        policy=policy,
    ).to_activation_runtime(
        selected_model_route=assistant.completion_model.get_model_route(),
        max_input_tokens=assistant.completion_model.max_input_tokens,
        supports_tool_calling=assistant.completion_model.supports_tool_calling,
    )

    prompt, attachments = await service.get_preflight_baseline(assistant.id)

    assert prompt == expected_runtime.prompt
    assert attachments == assistant.attachments


@pytest.mark.parametrize(
    (
        "selective_activation_enabled",
        "supports_tool_calling",
        "measurement",
        "message",
    ),
    [
        (
            False,
            True,
            SimpleNamespace(
                tokens=10,
                limit=1_000,
                source=TokenCountSource.LITELLM,
            ),
            "disabled by the organisation runtime policy",
        ),
        (
            True,
            False,
            SimpleNamespace(
                tokens=10,
                limit=1_000,
                source=TokenCountSource.LITELLM,
            ),
            "does not support on-demand Skills",
        ),
        (
            True,
            True,
            SimpleNamespace(
                tokens=1_001,
                limit=1_000,
                source=TokenCountSource.LITELLM,
            ),
            "exceeds the configured context allowance",
        ),
        (
            True,
            True,
            SimpleNamespace(
                tokens=10,
                limit=1_000,
                source=TokenCountSource.FALLBACK_ESTIMATE,
            ),
            "cannot measure the Skill catalogue exactly",
        ),
    ],
    ids=("disabled", "no-tool-support", "catalogue-too-large", "estimated"),
)
async def test_explicit_on_demand_change_rejects_runtime_fallbacks(
    selective_activation_enabled,
    supports_tool_calling,
    measurement,
    message,
    monkeypatch,
):
    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        lambda **_: measurement,
    )
    binding = _resolved_skill(
        name="On demand",
        position=0,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    resolution = SkillRuntimeResolution(eligible=(binding,), blocked=())
    assistant = _assistant_with_runtime_model()
    assistant.completion_model.supports_tool_calling = supports_tool_calling
    space = MagicMock()
    space.is_personal.return_value = False
    service = _service()
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        resolution
    )
    service.skill_service.create_turn_plan.side_effect = (
        lambda *, base_instructions, resolution: SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=selective_activation_enabled,
                max_attached_skills=100,
                context_share_percent=10,
                max_activations_per_turn=3,
            ),
        )
    )
    service._assert_persistent_baseline_fits = AsyncMock()

    with pytest.raises(BadRequestException, match=message):
        await service._validate_attachments_fit(
            assistant,
            space=space,
            explicit_on_demand_skill_ids=frozenset({binding.skill_id}),
        )

    service._assert_persistent_baseline_fits.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_on_demand_binding_remains_saveable_during_policy_drift(
    monkeypatch,
):
    measurement = SimpleNamespace(
        tokens=10,
        limit=1_000,
        source=TokenCountSource.LITELLM,
    )
    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        lambda **_: measurement,
    )
    binding = _resolved_skill(
        name="On demand",
        position=0,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    resolution = SkillRuntimeResolution(eligible=(binding,), blocked=())
    assistant = _assistant_with_runtime_model()
    space = MagicMock()
    space.is_personal.return_value = False
    service = _service()
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        resolution
    )
    service.skill_service.create_turn_plan.side_effect = (
        lambda *, base_instructions, resolution: SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=False,
                max_attached_skills=100,
                context_share_percent=10,
                max_activations_per_turn=3,
            ),
        )
    )
    service._assert_persistent_baseline_fits = AsyncMock()

    await service._validate_attachments_fit(
        assistant,
        space=space,
        explicit_on_demand_skill_ids=frozenset(),
    )

    service._assert_persistent_baseline_fits.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_on_demand_change_requires_an_effective_model():
    binding = _resolved_skill(
        name="On demand",
        position=0,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    assistant = _assistant_with_runtime_model()
    assistant.completion_model = None
    space = MagicMock()
    space.is_personal.return_value = False
    service = _service()
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        SkillRuntimeResolution(eligible=(binding,), blocked=())
    )

    with pytest.raises(
        BadRequestException,
        match="Choose a completion model before enabling on-demand Skills",
    ):
        await service._validate_attachments_fit(
            assistant,
            space=space,
            explicit_on_demand_skill_ids=frozenset({binding.skill_id}),
        )


@pytest.mark.asyncio
async def test_explicit_on_demand_change_rejects_an_execution_blocked_skill():
    binding = _resolved_skill(
        name="Blocked",
        position=0,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    assistant = _assistant_with_runtime_model()
    space = MagicMock()
    space.is_personal.return_value = False
    service = _service()
    service._resolve_effective_config = AsyncMock(return_value=None)
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        SkillRuntimeResolution(eligible=(), blocked=(binding,))
    )

    with pytest.raises(
        BadRequestException,
        match="Blocked organisation Skills cannot receive new or changed bindings",
    ):
        await service._validate_attachments_fit(
            assistant,
            space=space,
            explicit_on_demand_skill_ids=frozenset({binding.skill_id}),
        )


@pytest.mark.asyncio
async def test_skill_configuration_projects_saved_modes_and_exact_runtime(
    monkeypatch,
):
    measurement = SimpleNamespace(
        tokens=10,
        limit=1_000,
        source=TokenCountSource.LITELLM,
    )
    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        lambda **_: measurement,
    )
    binding = _resolved_skill(
        name="On demand",
        position=0,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    projection = SkillBindingProjection(binding=binding, execution_blocked=False)
    resolution = SkillRuntimeResolution(eligible=(binding,), blocked=())
    assistant = _assistant_with_runtime_model()
    space = MagicMock()
    space.is_personal.return_value = False
    space.get_assistant.return_value = assistant
    service = _service()
    service.space_repo.get_space_by_assistant.return_value = space
    service.skill_service.list_assistant_binding_projections.return_value = [projection]
    service.skill_service.resolve_assistant_bindings_for_runtime.return_value = (
        resolution
    )

    configuration = await service.get_skill_configuration(
        space_id=assistant.space_id,
        assistant_id=assistant.id,
    )

    assert configuration.bindings == (projection,)
    assert configuration.runtime is not None
    assert configuration.runtime.effective_model_id == assistant.completion_model.id
    assert (
        configuration.runtime.snapshot.effective_mode
        is SkillTurnEffectiveMode.SELECTIVE
    )
    assert configuration.runtime.snapshot.measurement is measurement


@pytest.mark.asyncio
async def test_personal_default_skill_configuration_has_no_direct_runtime():
    assistant = _assistant_with_runtime_model()
    assistant.is_default = True
    space = MagicMock()
    space.is_personal.return_value = True
    space.get_assistant.return_value = assistant
    service = _service()
    service.space_repo.get_space_by_assistant.return_value = space
    service.skill_service.list_assistant_binding_projections.return_value = []
    service._resolve_effective_config = AsyncMock()

    configuration = await service.get_skill_configuration(
        space_id=assistant.space_id,
        assistant_id=assistant.id,
    )

    assert configuration.bindings == ()
    assert configuration.runtime is None
    service._resolve_effective_config.assert_not_awaited()
    service.skill_service.create_turn_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_skill_configuration_authorizes_skill_read_before_runtime_resolution():
    service = _service()
    service.skill_service.list_assistant_binding_projections.side_effect = (
        UnauthorizedException("No Skill access")
    )

    with pytest.raises(UnauthorizedException, match="No Skill access"):
        await service.get_skill_configuration(
            space_id=uuid4(),
            assistant_id=uuid4(),
        )

    service.space_repo.get_space_by_assistant.assert_not_awaited()


# --- context fit: governance validates the model + prompt ask() will send ---


@pytest.mark.asyncio
async def test_fit_uses_governance_effective_model(monkeypatch):
    # Own model fits (100-token window), but governance steers to a 20-token
    # model: the save must be rejected against the model ask() will actually use.
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens", lambda **k: 15
    )
    small_model = SimpleNamespace(
        max_input_tokens=20,
        name="small",
        vision=False,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/small",
    )
    monkeypatch.setattr(
        "eneo.assistants.assistant_service.select_effective_completion_model",
        lambda **k: small_model,
    )
    service = _service()
    service._resolve_effective_config = AsyncMock(
        return_value=SimpleNamespace(
            models_enforced=True,
            prompt_enforced=False,
            enforced_prompt_text=None,
            governance_skill_resolution=SkillRuntimeResolution(
                eligible=(),
                blocked=(),
            ),
        )
    )
    # own ceiling 90 -> 15 fits; effective ceiling 10 -> 15 over -> reject
    with pytest.raises(BadRequestException):
        await service._validate_attachments_fit(
            _assistant_with(100, prompt_text="x"), space=MagicMock()
        )


@pytest.mark.asyncio
async def test_fit_uses_governance_enforced_prompt(monkeypatch):
    # Own prompt is empty (would fit), but governance enforces a long prompt
    # that ask() will send: the save must be rejected against that prompt.
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda text, *a, **k: len(text),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens", lambda **k: 0
    )
    service = _service()
    service._resolve_effective_config = AsyncMock(
        return_value=SimpleNamespace(
            models_enforced=False,
            prompt_enforced=True,
            enforced_prompt_text="x" * 95,
            governance_skill_resolution=SkillRuntimeResolution(
                eligible=(),
                blocked=(),
            ),
        )
    )
    # ceiling 90; enforced prompt is 95 chars -> 95 > 90 -> reject
    with pytest.raises(BadRequestException):
        await service._validate_attachments_fit(
            _assistant_with(100, n_attachments=0, prompt_text=None), space=MagicMock()
        )


@pytest.mark.asyncio
async def test_governance_preflight_uses_each_assistants_effective_model():
    allowed_current = SimpleNamespace(
        id=MagicMock(),
        max_input_tokens=100,
        name="allowed-current",
        vision=False,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/allowed-current",
    )
    policy_default = SimpleNamespace(
        id=MagicMock(),
        max_input_tokens=200,
        name="policy-default",
        vision=False,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/policy-default",
    )
    stale_model = SimpleNamespace(
        id=MagicMock(),
        max_input_tokens=300,
        name="stale",
        vision=False,
        supports_tool_calling=True,
        get_model_route=lambda: "openai/stale",
    )
    assistants = [
        SimpleNamespace(
            id=MagicMock(),
            is_default=True,
            completion_model=allowed_current,
            attachments=[],
            get_prompt_text=lambda: "first",
        ),
        SimpleNamespace(
            id=MagicMock(),
            is_default=True,
            completion_model=stale_model,
            attachments=[],
            get_prompt_text=lambda: "second",
        ),
    ]
    effective_config = SimpleNamespace(
        models_enforced=True,
        available_models=[allowed_current, policy_default],
        locked_model=None,
        policy_default_model=policy_default,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
        governance_skill_resolution=SkillRuntimeResolution(
            eligible=(),
            blocked=(),
        ),
    )
    service = _service()
    service.repo.get_personal_defaults_for_tenant.return_value = assistants
    service.effective_config_service = AsyncMock()
    service.effective_config_service.resolve_for.return_value = effective_config
    service._assert_persistent_baseline_fits = AsyncMock()

    await service.assert_personal_default_governance_context_fit()

    selected_models = [
        call.kwargs["model"]
        for call in service._assert_persistent_baseline_fits.await_args_list
    ]
    assert selected_models == [allowed_current, policy_default]
    service.effective_config_service.resolve_for.assert_awaited_once_with(
        assistants[0], space_is_personal=True
    )


# --- context fit: per-message ask-time guard (uploads have no save-time gate) ---


@pytest.mark.asyncio
async def test_message_fit_rejects_when_upload_alone_over_ceiling(monkeypatch):
    # A chat upload big enough to overflow on its own is rejected up front
    # instead of being inlined whole and failing at the provider.
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: len(text_files) * 100,
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=False)
    assistant = SimpleNamespace(attachments=[])
    # ceiling = 90; one uploaded text file = 100 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service()._assert_message_attachments_fit(
            assistant=assistant, model=model, prompt_text="", files=[_text_attachment()]
        )


@pytest.mark.asyncio
async def test_message_fit_passes_when_within_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: len(text_files) * 40,
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=False)
    assistant = SimpleNamespace(attachments=[])
    # ceiling = 90; one uploaded text file = 40 <= 90 -> ok
    await _service()._assert_message_attachments_fit(
        assistant=assistant, model=model, prompt_text="", files=[_text_attachment()]
    )


@pytest.mark.asyncio
async def test_message_fit_includes_persistent_baseline(monkeypatch):
    # An upload that fits alone is still rejected when the assistant's persistent
    # attachments leave no room — the request sends both on the same turn.
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: len(text_files) * 50,
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=False)
    assistant = SimpleNamespace(attachments=[_text_attachment()])
    # message alone = 50 <= 90; persistent 50 + message 50 = 100 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service()._assert_message_attachments_fit(
            assistant=assistant, model=model, prompt_text="", files=[_text_attachment()]
        )


@pytest.mark.asyncio
async def test_message_fit_skips_when_no_uploads(monkeypatch):
    # The hot text-only chat path does no token work: nothing was uploaded, the
    # baseline was gated on save, and history is budget-evicted downstream.
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens", lambda *a, **k: 10**9
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **k: 10**9,
    )
    file_service = AsyncMock()
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=True)
    assistant = SimpleNamespace(attachments=[_text_attachment()])
    # Would raise (and touch derived images) if it ran -> proves the early return.
    await _service(file_service)._assert_message_attachments_fit(
        assistant=assistant, model=model, prompt_text="x", files=[]
    )
    file_service.with_derived_images.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_fit_rechecks_skill_baseline_without_uploads(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 95)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens", lambda **k: 0
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=False)
    assistant = SimpleNamespace(attachments=[])

    with pytest.raises(BadRequestException):
        await _service()._assert_message_attachments_fit(
            assistant=assistant,
            model=model,
            prompt_text="Skill prompt",
            files=[],
            validate_persistent_baseline=True,
        )


@pytest.mark.asyncio
async def test_message_fit_counts_derived_images_for_vision(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: len(text_files) * 10
        + len(image_files) * 90,
    )
    text_file = _text_attachment()
    derived_image = _image_attachment()
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[text_file, derived_image]
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=True)
    # No persistent attachments, so the only derived-image lookup is the upload's.
    assistant = SimpleNamespace(attachments=[])
    # ceiling = 90; text 10 + derived image 90 = 100 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service(file_service)._assert_message_attachments_fit(
            assistant=assistant, model=model, prompt_text="", files=[text_file]
        )
    file_service.with_derived_images.assert_awaited()


@pytest.mark.asyncio
async def test_message_fit_no_derived_images_without_vision(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr("eneo.files.attachment_budget.count_tokens", lambda *a, **k: 0)
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: len(text_files) * 10
        + len(image_files) * 90,
    )
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[_text_attachment(), _image_attachment()]
    )
    model = SimpleNamespace(max_input_tokens=100, name="gpt-4o", vision=False)
    assistant = SimpleNamespace(attachments=[])
    # Non-vision: uploaded file used as-is (10 <= 90), no derived-image lookup.
    await _service(file_service)._assert_message_attachments_fit(
        assistant=assistant, model=model, prompt_text="", files=[_text_attachment()]
    )
    file_service.with_derived_images.assert_not_awaited()


# --- assembler advertises the attachment guardrails (count + size) ---


def test_assembler_advertises_attachment_guardrails(monkeypatch):
    # The fit ceiling is no longer advertised here — it depends on the live
    # model window and is derived client-side. The assembler advertises only the
    # model-independent guardrails (count + byte size).
    from eneo.assistants.api.assistant_assembler import AssistantAssembler

    monkeypatch.setattr(
        "eneo.assistants.api.assistant_assembler.get_settings",
        lambda: _settings(attachment_max_files=100, attachment_max_size_bytes=123),
    )
    assembler = AssistantAssembler(user=MagicMock(), prompt_assembler=MagicMock())

    restrictions = assembler._get_allowed_attachments()
    assert restrictions.limit.max_files == 100
    assert restrictions.limit.max_size == 123
