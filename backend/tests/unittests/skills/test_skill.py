import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.completion_models.domain.skill_activation import (
    SKILL_ACTIVATION_TOOL_NAME,
    ProviderToolCall,
)
from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain.model_route import MAX_MODEL_ROUTE_LENGTH
from eneo.skills import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    ResolvedSkillBinding,
    compose_skill_instructions,
    create_content_digest,
    normalize_skill_content,
    validate_skill_slug,
)
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import (
    NormalizedSkillContent,
    Skill,
    SkillActivationEvidenceV1,
    SkillActivationMode,
    SkillBindingReference,
    SkillBindingSource,
    SkillExecutionBlock,
    SkillExecutionBlockedException,
    SkillExecutionReference,
    SkillPublicationState,
    SkillRevision,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
    SkillTurnEffectiveMode,
    SkillTurnPlan,
)

SKILL_ACTIVATION_EVIDENCE_SIZE_BUDGET_BYTES = 400_000


def _binding(*, position: int, name: str = "Payroll") -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug=name.lower(),
        revision_number=1,
        current_revision_number=1,
        display_name=name,
        instructions=f"Instructions for {name}",
        content_digest="a" * 64,
        position=position,
        source=SkillBindingSource.SPACE,
    )


def _activation_evidence(
    plan: SkillTurnPlan,
    *,
    selected_model_id: UUID | None = None,
    selected_model_route: str = "openai/gpt-4o",
) -> SkillActivationEvidenceV1:
    runtime = plan.to_activation_runtime(
        selected_model_route=selected_model_route,
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    return plan.activation_evidence(
        selected_model_id=selected_model_id or uuid4(),
        selected_model_route=selected_model_route,
        snapshot=runtime.snapshot(),
    )


def _service(repo: AsyncMock) -> SkillService:
    if not isinstance(repo.list_active_execution_blocks.return_value, dict):
        repo.list_active_execution_blocks.return_value = {}
    return SkillService(
        user=MagicMock(tenant_id=uuid4()),
        repo=repo,
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
    )


def _reference(
    binding: ResolvedSkillBinding, *, position: int | None = None
) -> SkillExecutionReference:
    return SkillExecutionReference(
        skill_id=binding.skill_id,
        skill_revision_id=binding.skill_revision_id,
        revision_number=binding.revision_number,
        content_digest=binding.content_digest,
        position=binding.position if position is None else position,
    )


def _execution_block(*, tenant_id, binding: ResolvedSkillBinding):
    now = datetime.now(timezone.utc)
    return SkillExecutionBlock(
        id=uuid4(),
        tenant_id=tenant_id,
        skill_space_id=binding.skill_space_id,
        skill_id=binding.skill_id,
        blocked_by_user_id=uuid4(),
        reason="Confirmed unsafe instructions",
        blocked_at=now,
    )


def _skill(
    *,
    current_revision_number: int = 1,
    published_revision_number: int | None = None,
    first_published_at: datetime | None = None,
) -> Skill:
    skill_id = uuid4()
    now = datetime.now(timezone.utc)
    revision = SkillRevision(
        id=uuid4(),
        skill_id=skill_id,
        revision_number=current_revision_number,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
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
        published_revision_number=published_revision_number,
        first_published_at=first_published_at,
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
        current_revision=revision,
    )


@pytest.mark.parametrize(
    "slug",
    ["payroll", "payroll-questions", "skill-2", "2fa-guidance"],
)
def test_validate_skill_slug_accepts_agent_skills_name_grammar(slug: str):
    assert validate_skill_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    ["", "Payroll", "pay_roll", "-payroll", "payroll-", "payroll--questions"],
)
def test_validate_skill_slug_rejects_invalid_values(slug: str):
    with pytest.raises(BadRequestException):
        validate_skill_slug(slug)


def test_normalize_skill_content_preserves_markdown_and_normalizes_newlines():
    assert normalize_skill_content(
        display_name="  Payroll  ",
        description="  Answers payroll questions  ",
        instructions="  # Rules\r\n\r\nUse the handbook.  ",
    ) == (
        "Payroll",
        "Answers payroll questions",
        "# Rules\n\nUse the handbook.",
    )


def test_normalized_skill_content_keeps_validation_and_digest_together():
    content = NormalizedSkillContent.create(
        display_name=" Payroll ",
        description=" Approved payroll guidance ",
        instructions=" First step\r\nSecond step ",
    )

    assert content.display_name == "Payroll"
    assert content.description == "Approved payroll guidance"
    assert content.instructions == "First step\nSecond step"
    assert content.content_digest == create_content_digest(
        display_name=content.display_name,
        description=content.description,
        instructions=content.instructions,
    )


def test_normalize_skill_content_enforces_specification_description_bound():
    with pytest.raises(BadRequestException):
        normalize_skill_content(
            display_name="Payroll",
            description="x" * (MAX_SKILL_DESCRIPTION_LENGTH + 1),
            instructions="instructions",
        )


def test_normalize_skill_content_does_not_apply_arbitrary_line_or_character_caps():
    instructions = "\n".join(["A focused instruction."] * 600)
    _, _, normalized = normalize_skill_content(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions=instructions,
    )
    assert normalized == instructions


def test_content_digest_is_stable_and_covers_all_revision_content():
    digest = create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the handbook.",
    )
    assert digest == create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the handbook.",
    )
    assert digest != create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the current handbook.",
    )


@pytest.mark.parametrize(
    ("skill", "expected"),
    [
        (_skill(), SkillPublicationState.DRAFT),
        (
            _skill(
                published_revision_number=1,
                first_published_at=datetime.now(timezone.utc),
            ),
            SkillPublicationState.PUBLISHED,
        ),
        (
            _skill(
                current_revision_number=2,
                published_revision_number=1,
                first_published_at=datetime.now(timezone.utc),
            ),
            SkillPublicationState.UPDATE_PENDING,
        ),
        (
            _skill(first_published_at=datetime.now(timezone.utc)),
            SkillPublicationState.UNPUBLISHED,
        ),
    ],
)
def test_publication_state_is_derived_from_exact_revision_pointer(
    skill: Skill, expected: SkillPublicationState
):
    assert skill.publication_state is expected


def test_zero_skills_returns_base_prompt_byte_for_byte():
    base = "  Base instructions\n"
    composition = compose_skill_instructions(base_instructions=base, bindings=[])
    assert composition.prompt == base
    assert composition.provenance == ()


def test_activation_mode_is_dormant_in_composition():
    always = [_binding(position=0, name="Payroll"), _binding(position=1, name="Leave")]
    on_demand = [
        replace(binding, activation_mode=SkillActivationMode.ON_DEMAND)
        for binding in always
    ]

    assert compose_skill_instructions(
        base_instructions="Base instructions", bindings=on_demand
    ) == compose_skill_instructions(
        base_instructions="Base instructions", bindings=always
    )


def test_turn_plan_freezes_bindings_and_starts_with_required_skills():
    always = _binding(position=0, name="Payroll")
    on_demand = replace(
        _binding(position=1, name="Leave"),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    blocked = _binding(position=2, name="Incident")
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=15,
        max_activations_per_turn=5,
    )

    plan = SkillTurnPlan.create(
        base_instructions="Base instructions",
        resolution=SkillRuntimeResolution(
            eligible=(always, on_demand),
            blocked=(blocked,),
        ),
        policy=policy,
    )

    assert plan.composition == compose_skill_instructions(
        base_instructions="Base instructions",
        bindings=[always],
    )
    assert [binding.binding for binding in plan.available] == [always, on_demand]
    assert [binding.activation_key for binding in plan.available] == [
        "skill-1",
        "skill-2",
    ]
    assert all(
        str(binding.binding.skill_id) not in binding.activation_key
        for binding in plan.available
    )
    with pytest.raises(FrozenInstanceError):
        plan.base_instructions = "Changed"  # type: ignore[misc]

    evidence = _activation_evidence(plan)
    assert evidence.effective_mode == "selective"
    assert [reference.skill_id for reference in evidence.available] == [
        always.skill_id,
        on_demand.skill_id,
    ]
    assert [reference.skill_id for reference in evidence.blocked] == [blocked.skill_id]
    assert evidence.initially_active == ("skill-1",)
    assert evidence.accepted == ()
    assert evidence.repeated == ()
    assert evidence.rejected == ()
    assert "Instructions for" not in evidence.model_dump_json()
    assert "Confirmed unsafe instructions" not in evidence.model_dump_json()


def test_turn_plan_stages_all_blocked_bindings_for_full_save_validation():
    blocked_always = replace(
        _binding(position=0, name="Blocked required"),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    blocked_on_demand = replace(
        _binding(position=1, name="Blocked optional"),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    available_always = replace(
        _binding(position=2, name="Available required"),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    available_on_demand = replace(
        _binding(position=3, name="Available optional"),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=15,
        max_activations_per_turn=5,
    )
    plan = SkillTurnPlan.create(
        base_instructions="Base instructions",
        resolution=SkillRuntimeResolution(
            eligible=(available_always, available_on_demand),
            blocked=(blocked_always, blocked_on_demand),
        ),
        policy=policy,
    )

    validation_plan = plan.for_full_save_validation()

    assert [binding.binding for binding in validation_plan.available] == [
        blocked_always,
        blocked_on_demand,
        available_always,
        available_on_demand,
    ]
    assert [binding.activation_key for binding in validation_plan.available] == [
        "skill-1",
        "skill-2",
        "skill-3",
        "skill-4",
    ]
    assert validation_plan.initially_active_keys == ("skill-1", "skill-3")
    assert validation_plan.blocked == ()
    assert [binding.binding for binding in plan.available] == [
        available_always,
        available_on_demand,
    ]
    assert [binding.binding for binding in plan.blocked] == [
        blocked_always,
        blocked_on_demand,
    ]


def test_zero_skill_turn_plan_preserves_base_and_records_empty_evidence():
    plan = SkillTurnPlan.create(
        base_instructions="  Base instructions\n",
        resolution=SkillRuntimeResolution(eligible=(), blocked=()),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )

    evidence = _activation_evidence(plan)

    assert plan.composition.prompt == "  Base instructions\n"
    assert plan.composition.provenance == ()
    assert evidence.available == ()
    assert evidence.blocked == ()
    assert evidence.initially_active == ()
    assert evidence.skill_context_tokens >= 0


def test_skill_activation_evidence_round_trips_strict_versioned_body_free_json():
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(_binding(position=0),),
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )
    evidence = _activation_evidence(plan)

    assert type(evidence).model_validate_json(evidence.model_dump_json()) == evidence

    dumped = evidence.model_dump(mode="json")
    for invalid in (
        {**dumped, "version": 2},
        {**dumped, "effective_mode": "unknown"},
        {**dumped, "unexpected": True},
        {
            **dumped,
            "rejected": [
                {
                    "activation_key": "skill-1",
                    "reason": "unknown_reason",
                }
            ],
        },
    ):
        with pytest.raises(ValidationError):
            type(evidence).model_validate(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("skill_context_tokens", "42"),
        ("skill_context_token_limit", "100"),
        ("activation_rounds", "0"),
        ("selection_latency_ms", "0"),
    ],
)
def test_skill_activation_evidence_rejects_coerced_numeric_counters(
    field: str,
    value: str,
):
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(_binding(position=0),),
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )
    evidence = _activation_evidence(plan)
    dumped = evidence.model_dump(mode="json")

    with pytest.raises(ValidationError):
        type(evidence).model_validate({**dumped, field: value})


def test_skill_activation_reference_rejects_coerced_numeric_identity():
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(_binding(position=0),),
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )
    evidence = _activation_evidence(plan)
    dumped = evidence.model_dump(mode="json")
    dumped["available"][0]["revision_number"] = "1"

    with pytest.raises(ValidationError):
        type(evidence).model_validate(dumped)


def test_skill_activation_evidence_rejects_duplicate_reference_catalogue_entries():
    binding = _binding(position=0)
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(binding,),
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )
    evidence = _activation_evidence(plan)
    dumped = evidence.model_dump(mode="json")
    dumped["blocked"] = dumped["available"]

    with pytest.raises(ValidationError, match="both available and blocked"):
        type(evidence).model_validate(dumped)


def test_skill_activation_evidence_stays_compact_at_attachment_ceiling():
    bindings = tuple(
        _binding(position=position, name=f"Skill-{position}")
        for position in range(1000)
    )
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=bindings,
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=1000,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )
    evidence = _activation_evidence(
        plan,
        selected_model_route="m" * MAX_MODEL_ROUTE_LENGTH,
    )

    serialized = json.dumps(evidence.model_dump(mode="json"), separators=(",", ":"))

    assert len(serialized) < SKILL_ACTIVATION_EVIDENCE_SIZE_BUDGET_BYTES


def test_skill_activation_evidence_rejects_an_oversized_model_route():
    binding = _binding(position=0)
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(binding,),
            blocked=(),
        ),
        policy=SkillRuntimePolicy(
            selective_activation_enabled=False,
            max_attached_skills=100,
            context_share_percent=10,
            max_activations_per_turn=10,
        ),
    )

    with pytest.raises(ValidationError, match="selected_model_route"):
        plan.activation_evidence(
            selected_model_id=uuid4(),
            selected_model_route="m" * (MAX_MODEL_ROUTE_LENGTH + 1),
            snapshot=plan.to_activation_runtime(
                selected_model_route="openai/gpt-4o",
                max_input_tokens=128_000,
                supports_tool_calling=True,
            ).snapshot(),
        )


def test_composition_orders_skills_and_builds_matching_provenance():
    second = _binding(position=1, name="Absence")
    first = _binding(position=0, name="Payroll")

    composition = compose_skill_instructions(
        base_instructions="Base instructions", bindings=[second, first]
    )

    assert composition.prompt.startswith("Base instructions\n\n")
    assert composition.prompt.index("### Skill: Payroll") < composition.prompt.index(
        "### Skill: Absence"
    )
    assert [reference.skill_id for reference in composition.provenance] == [
        first.skill_id,
        second.skill_id,
    ]
    assert "Instructions for Payroll" not in repr(composition.provenance)


def test_composition_rejects_duplicate_positions():
    with pytest.raises(BadRequestException, match="positions must be unique"):
        compose_skill_instructions(
            base_instructions="Base",
            bindings=[_binding(position=0), _binding(position=0, name="Absence")],
        )


def test_composition_rejects_duplicate_skill_identity():
    binding = _binding(position=0)
    duplicate = ResolvedSkillBinding(
        skill_id=binding.skill_id,
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=binding.skill_space_id,
        slug="payroll",
        revision_number=2,
        current_revision_number=2,
        display_name="Payroll",
        instructions="Updated instructions",
        content_digest="b" * 64,
        position=1,
        source=SkillBindingSource.SPACE,
    )
    with pytest.raises(BadRequestException, match="only be bound once"):
        compose_skill_instructions(
            base_instructions="Base", bindings=[binding, duplicate]
        )


async def test_execution_snapshot_with_no_skills_preserves_base_without_repo_read():
    repo = AsyncMock()

    composition = await _service(repo).compose_for_execution_snapshot(
        tenant_id=uuid4(),
        space_id=uuid4(),
        provenance=(),
        base_instructions="  Base instructions\n",
    )

    assert composition.prompt == "  Base instructions\n"
    assert composition.provenance == ()
    repo.resolve_references_for_execution_snapshot.assert_not_awaited()


async def test_execution_snapshot_uses_persisted_order_and_allows_inactive_skill():
    payroll = replace(_binding(position=0, name="Payroll"), is_active=False)
    absence = _binding(position=1, name="Absence")
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = [payroll, absence]
    tenant_id = uuid4()
    space_id = uuid4()

    composition = await _service(repo).compose_for_execution_snapshot(
        tenant_id=tenant_id,
        space_id=space_id,
        provenance=(
            _reference(absence, position=20),
            _reference(payroll, position=10),
        ),
        base_instructions="Base",
    )

    repo.resolve_references_for_execution_snapshot.assert_awaited_once_with(
        tenant_id=tenant_id,
        parent_space_id=space_id,
        references=[
            SkillBindingReference(
                skill_id=payroll.skill_id,
                skill_revision_id=payroll.skill_revision_id,
            ),
            SkillBindingReference(
                skill_id=absence.skill_id,
                skill_revision_id=absence.skill_revision_id,
            ),
        ],
    )
    assert composition.prompt.index("### Skill: Payroll") < composition.prompt.index(
        "### Skill: Absence"
    )
    assert [reference.position for reference in composition.provenance] == [10, 20]


async def test_assistant_composition_excludes_blocked_skill_without_changing_bindings():
    blocked = _binding(position=0, name="Payroll")
    allowed = _binding(position=1, name="Absence")
    tenant_id = uuid4()
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [blocked, allowed]
    repo.list_active_execution_blocks.return_value = {
        blocked.skill_id: _execution_block(tenant_id=tenant_id, binding=blocked)
    }
    service = _service(repo)
    service.user.tenant_id = tenant_id

    resolution = await service.resolve_assistant_bindings_for_runtime(
        assistant_id=uuid4()
    )
    composition = compose_skill_instructions(
        base_instructions="Base",
        bindings=list(resolution.eligible),
    )

    assert "Payroll" not in composition.prompt
    assert "Absence" in composition.prompt
    assert [reference.skill_id for reference in composition.provenance] == [
        allowed.skill_id
    ]
    repo.replace_assistant_bindings.assert_not_awaited()


async def test_runtime_composition_keeps_all_bindings_without_execution_blocks():
    binding = _binding(position=0, name="Payroll")
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [binding]
    repo.list_app_bindings_for_execution_plan.return_value = [binding]
    repo.list_policy_bindings.return_value = [binding]
    repo.list_active_execution_blocks.return_value = {}
    service = _service(repo)

    assistant_resolution = await service.resolve_assistant_bindings_for_runtime(
        assistant_id=uuid4()
    )
    assistant = compose_skill_instructions(
        base_instructions="Assistant base",
        bindings=list(assistant_resolution.eligible),
    )
    app = await service.compose_for_app(
        app_id=uuid4(),
        base_instructions="App base",
    )
    policy = await service.compose_for_policy(
        policy_id=uuid4(),
        base_instructions="Policy base",
    )

    assert [reference.skill_id for reference in assistant.provenance] == [
        binding.skill_id
    ]
    assert [reference.skill_id for reference in app.provenance] == [binding.skill_id]
    assert [reference.skill_id for reference in policy.provenance] == [binding.skill_id]


async def test_policy_runtime_resolution_retains_blocked_revision_without_reason():
    blocked = _binding(position=0, name="Payroll")
    allowed = _binding(position=1, name="Absence")
    tenant_id = uuid4()
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [blocked, allowed]
    repo.list_active_execution_blocks.return_value = {
        blocked.skill_id: _execution_block(tenant_id=tenant_id, binding=blocked)
    }
    service = _service(repo)
    service.user.tenant_id = tenant_id

    resolution = await service.resolve_governance_bindings_for_runtime(
        policy_id=uuid4()
    )

    assert resolution.eligible == (allowed,)
    assert resolution.blocked == (blocked,)
    assert "Confirmed unsafe instructions" not in repr(resolution)
    repo.replace_policy_bindings.assert_not_awaited()


async def test_turn_plan_reads_stored_policy_once_and_preserves_dormant_modes():
    binding = replace(
        _binding(position=0),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=20,
        max_activations_per_turn=5,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [binding]
    repo.list_active_execution_blocks.return_value = {}
    repo.get_or_seed_runtime_policy.return_value = policy
    service = _service(repo)

    resolution = await service.resolve_assistant_bindings_for_runtime(
        assistant_id=uuid4()
    )
    plan = await service.create_turn_plan(
        base_instructions="Base",
        resolution=resolution,
    )

    assert plan.policy is policy
    assert plan.available[0].binding is binding
    assert plan.composition == compose_skill_instructions(
        base_instructions="Base",
        bindings=[],
    )
    runtime = plan.to_activation_runtime(
        selected_model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    assert runtime.tool_definition is not None
    assert binding.instructions not in runtime.prompt
    repo.get_or_seed_runtime_policy.assert_awaited_once_with(
        tenant_id=service.user.tenant_id
    )


def test_turn_plan_freezes_hidden_blocked_keys_and_maps_runtime_evidence():
    always = replace(
        _binding(position=0, name="Safety"),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    optional = replace(
        _binding(position=1, name="Payroll"),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    blocked = replace(
        _binding(position=2, name="Blocked"),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=100,
        context_share_percent=20,
        max_activations_per_turn=2,
    )
    plan = SkillTurnPlan.create(
        base_instructions="Base",
        resolution=SkillRuntimeResolution(
            eligible=(always, optional),
            blocked=(blocked,),
        ),
        policy=policy,
    )

    assert plan.initially_active_keys == ("skill-1",)
    assert plan.blocked[0].activation_key == "blocked-skill-1"
    assert plan.blocked[0].activation_key not in {
        binding.activation_key for binding in plan.available
    }
    runtime = plan.to_activation_runtime(
        selected_model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    runtime.apply_provider_tool_calls(
        calls=(
            ProviderToolCall(
                call_id="activate",
                name=SKILL_ACTIVATION_TOOL_NAME,
                arguments='{"skill_key":"skill-2"}',
            ),
        ),
        messages=[{"role": "system", "content": runtime.prompt}],
    )
    evidence = plan.activation_evidence(
        selected_model_id=uuid4(),
        selected_model_route="openai/gpt-4o",
        snapshot=runtime.snapshot(),
    )

    assert evidence.effective_mode is SkillTurnEffectiveMode.SELECTIVE
    assert evidence.initially_active == ("skill-1",)
    assert evidence.accepted == ("skill-2",)
    assert evidence.blocked[0].activation_key == "blocked-skill-1"
    assert [
        reference.skill_revision_id
        for reference in plan.active_provenance(runtime.snapshot())
    ] == [always.skill_revision_id, optional.skill_revision_id]


async def test_execution_snapshot_hides_incident_reason_when_skill_is_blocked():
    binding = _binding(position=0)
    reference = _reference(binding)
    tenant_id = uuid4()
    block = _execution_block(tenant_id=tenant_id, binding=binding)
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = [binding]
    repo.list_active_execution_blocks.return_value = {binding.skill_id: block}

    with pytest.raises(SkillExecutionBlockedException) as exc_info:
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=tenant_id,
            space_id=uuid4(),
            provenance=(reference,),
            base_instructions="Base",
        )

    assert block.reason not in str(exc_info.value)
    assert exc_info.value.block_id == block.id
    assert exc_info.value.skill_id == binding.skill_id
    assert exc_info.value.reason == block.reason


@pytest.mark.parametrize("field", ["revision_number", "content_digest"])
async def test_execution_snapshot_rejects_changed_revision_metadata(field: str):
    binding = _binding(position=0)
    reference = _reference(binding)
    replacement = 2 if field == "revision_number" else "b" * 64
    reference = replace(reference, **{field: replacement})
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = [binding]

    with pytest.raises(BadRequestException, match="metadata no longer matches"):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=(reference,),
            base_instructions="Base",
        )


async def test_execution_snapshot_rejects_missing_revision():
    binding = _binding(position=0)
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = []

    with pytest.raises(BadRequestException, match="no longer available"):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=(_reference(binding),),
            base_instructions="Base",
        )


@pytest.mark.parametrize("invalid", ["duplicate_position", "duplicate_skill"])
async def test_execution_snapshot_rejects_invalid_persisted_order(invalid: str):
    first = _binding(position=0, name="Payroll")
    second = _binding(position=1, name="Absence")
    if invalid == "duplicate_position":
        provenance = (_reference(first), _reference(second, position=0))
    else:
        provenance = (
            _reference(first),
            replace(
                _reference(second),
                skill_id=first.skill_id,
            ),
        )
    repo = AsyncMock()

    with pytest.raises(BadRequestException):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=provenance,
            base_instructions="Base",
        )
    repo.resolve_references_for_execution_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_attached_skills", 0),
        ("max_attached_skills", 1001),
        ("context_share_percent", 0),
        ("context_share_percent", 101),
        ("max_activations_per_turn", 0),
        ("max_activations_per_turn", 11),
    ],
)
def test_runtime_policy_bounds_are_enforced_by_the_domain(field: str, value: int):
    values = {
        "selective_activation_enabled": False,
        "max_attached_skills": 100,
        "context_share_percent": 10,
        "max_activations_per_turn": 10,
        field: value,
    }
    with pytest.raises(BadRequestException, match="must be between"):
        SkillRuntimePolicy(
            selective_activation_enabled=bool(values["selective_activation_enabled"]),
            max_attached_skills=int(values["max_attached_skills"]),
            context_share_percent=int(values["context_share_percent"]),
            max_activations_per_turn=int(values["max_activations_per_turn"]),
        )
