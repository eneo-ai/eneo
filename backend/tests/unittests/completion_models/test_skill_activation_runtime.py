import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.skill_activation import (
    SKILL_ACTIVATION_TOOL_NAME,
    FrozenSkillInstruction,
    InvalidSkillToolCallError,
    ProviderToolCall,
    SkillActivationFallbackReason,
    SkillActivationRejectionReason,
    SkillActivationRejectionSnapshot,
    SkillActivationRequest,
    SkillActivationRoundResult,
    SkillActivationRuntime,
    SkillPromptOwnershipError,
    SkillTurnEffectiveMode,
)
from eneo.completion_models.domain.skill_context import (
    SkillContextMeasurement,
    measure_skill_context,
)
from eneo.skills.domain.skill import (
    MAX_SKILL_ACTIVATIONS_PER_TURN,
    ResolvedSkillBinding,
    SkillBindingSource,
)
from eneo.tokens.token_utils import TokenCount, TokenCountSource


def _skill(
    *,
    key: str,
    name: str,
    description: str,
    position: int,
    instructions: str,
    initially_active: bool,
) -> FrozenSkillInstruction:
    return FrozenSkillInstruction(
        activation_key=key,
        binding=ResolvedSkillBinding(
            skill_id=uuid4(),
            skill_revision_id=uuid4(),
            current_revision_id=uuid4(),
            skill_space_id=uuid4(),
            slug=name.lower().replace(" ", "-"),
            revision_number=1,
            current_revision_number=1,
            display_name=name,
            description=description,
            instructions=instructions,
            content_digest="a" * 64,
            position=position,
            source=SkillBindingSource.SPACE,
        ),
        initially_active=initially_active,
    )


def _apply_activation_requests(
    runtime: SkillActivationRuntime,
    *requests: tuple[str, str | None],
) -> list[dict[str, bool]]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": runtime.prompt},
    ]
    runtime.apply_provider_tool_calls(
        calls=tuple(
            ProviderToolCall(
                call_id=call_id,
                name=SKILL_ACTIVATION_TOOL_NAME,
                arguments=json.dumps({"skill_key": activation_key}),
            )
            for call_id, activation_key in requests
        ),
        messages=messages,
    )
    return [
        json.loads(str(message["content"]))
        for message in messages
        if message.get("role") == "tool"
    ]


def test_selective_runtime_advertises_descriptors_without_instruction_bodies():
    always = _skill(
        key="skill-1",
        name="Safety",
        description="Required safety rules",
        position=0,
        instructions="Never reveal the safety body.",
        initially_active=True,
    )
    on_demand = _skill(
        key="skill-2",
        name="Payroll",
        description="Use for payroll and salary questions",
        position=1,
        instructions="Secret payroll instructions.",
        initially_active=False,
    )

    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(always, on_demand),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=3,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )

    tool = runtime.tool_definition
    snapshot = runtime.snapshot()

    assert snapshot.effective_mode is SkillTurnEffectiveMode.SELECTIVE
    assert snapshot.fallback_reason is None
    assert snapshot.initially_active == ("skill-1",)
    assert runtime.prompt.index("Safety") > runtime.prompt.index("Base")
    assert "Never reveal the safety body." in runtime.prompt
    assert "Secret payroll instructions." not in runtime.prompt
    assert tool is not None
    assert "__" not in tool.name
    assert "skill-2" in tool.description
    assert "Payroll" in tool.description
    assert "Use for payroll and salary questions" in tool.description
    assert "Secret payroll instructions." not in tool.description
    assert tool.schema["properties"]["skill_key"]["enum"] == ["skill-2"]


def test_runtime_without_native_tool_calls_keeps_only_required_skills():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Safety",
                description="Required",
                position=0,
                instructions="Always body",
                initially_active=True,
            ),
            _skill(
                key="skill-2",
                name="Payroll",
                description="Optional",
                position=1,
                instructions="On-demand body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=3,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=False,
    )

    snapshot = runtime.snapshot()

    assert snapshot.effective_mode is SkillTurnEffectiveMode.ALWAYS_ONLY
    assert (
        snapshot.fallback_reason
        is SkillActivationFallbackReason.MODEL_LACKS_TOOL_CALLING
    )
    assert runtime.tool_definition is None
    assert "Always body" in runtime.prompt
    assert "On-demand body" not in runtime.prompt


def test_descriptor_overflow_falls_back_atomically_instead_of_advertising_a_prefix():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=tuple(
            _skill(
                key=f"skill-{index}",
                name=f"Skill {index}",
                description="Distinct descriptor " * 20,
                position=index,
                instructions=f"Body {index}",
                initially_active=False,
            )
            for index in range(1, 4)
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=3,
        context_share_percent=1,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )

    snapshot = runtime.snapshot()

    assert snapshot.effective_mode is SkillTurnEffectiveMode.ALWAYS_ONLY
    assert (
        snapshot.fallback_reason
        is SkillActivationFallbackReason.CATALOG_BUDGET_EXCEEDED
    )
    assert runtime.tool_definition is None
    assert not any(f"Body {index}" in runtime.prompt for index in range(1, 4))


def test_selective_runtime_falls_back_when_catalogue_fit_cannot_be_measured():
    with patch(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        return_value=SkillContextMeasurement(
            tokens=1,
            limit=100,
            source=TokenCountSource.FALLBACK_ESTIMATE,
        ),
    ):
        runtime = SkillActivationRuntime.create(
            base_instructions="Base",
            skills=(
                _skill(
                    key="skill-1",
                    name="Payroll",
                    description="給与と報酬に関する質問",
                    position=1,
                    instructions="給与データを確認する",
                    initially_active=False,
                ),
            ),
            blocked_keys=frozenset(),
            selective_activation_enabled=True,
            max_activations_per_turn=1,
            context_share_percent=10,
            model_route="custom/unknown",
            max_input_tokens=1_000,
            supports_tool_calling=True,
        )

    snapshot = runtime.snapshot()
    assert snapshot.effective_mode is SkillTurnEffectiveMode.ALWAYS_ONLY
    assert (
        snapshot.fallback_reason
        is SkillActivationFallbackReason.TOKEN_MEASUREMENT_UNAVAILABLE
    )
    assert runtime.tool_definition is None


def test_activation_rejects_candidate_when_fit_cannot_be_measured():
    with patch(
        "eneo.completion_models.domain.skill_activation.measure_skill_context",
        side_effect=(
            SkillContextMeasurement(
                tokens=1,
                limit=100,
                source=TokenCountSource.LITELLM,
            ),
            SkillContextMeasurement(
                tokens=1,
                limit=100,
                source=TokenCountSource.FALLBACK_ESTIMATE,
            ),
        ),
    ):
        runtime = SkillActivationRuntime.create(
            base_instructions="Base",
            skills=(
                _skill(
                    key="skill-1",
                    name="Payroll",
                    description="給与と報酬に関する質問",
                    position=1,
                    instructions="給与データを確認する",
                    initially_active=False,
                ),
            ),
            blocked_keys=frozenset(),
            selective_activation_enabled=True,
            max_activations_per_turn=1,
            context_share_percent=10,
            model_route="custom/unknown",
            max_input_tokens=1_000,
            supports_tool_calling=True,
        )
        decisions = _apply_activation_requests(runtime, ("activate", "skill-1"))

    assert decisions[0] == {
        "activated": False,
        "unavailable": True,
    }
    snapshot = runtime.snapshot()
    assert snapshot.accepted == ()
    assert snapshot.active == ()
    assert snapshot.rejected[0].reason is (
        SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE
    )


def test_fresh_candidate_assessment_matches_accepted_first_activation():
    candidate = _skill(
        key="skill-1",
        name="Payroll",
        description="Payroll questions",
        position=1,
        instructions="Use the approved payroll procedure.",
        initially_active=False,
    )
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(candidate,),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=8_000,
        supports_tool_calling=True,
    )

    assessments = runtime.assess_on_demand_candidates(
        frozenset({candidate.binding.skill_id})
    )

    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.skill_id == candidate.binding.skill_id
    assert assessment.activation_key == candidate.activation_key
    assert assessment.rejection_reason is None
    assert runtime.snapshot().active == ()

    decisions = _apply_activation_requests(runtime, ("activate", "skill-1"))

    assert decisions == [{"activated": True}]
    assert runtime.prompt == assessment.prompt
    assert runtime.snapshot().measurement == assessment.measurement


def test_fresh_candidate_assessment_matches_oversized_first_activation_rejection():
    candidate = _skill(
        key="skill-1",
        name="Oversized",
        description="A compact descriptor",
        position=1,
        instructions="large " * 20_000,
        initially_active=False,
    )
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(candidate,),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=2_000,
        supports_tool_calling=True,
    )

    assessments = runtime.assess_on_demand_candidates(
        frozenset({candidate.binding.skill_id})
    )

    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.skill_id == candidate.binding.skill_id
    assert assessment.activation_key == candidate.activation_key
    assert assessment.rejection_reason is (
        SkillActivationRejectionReason.CONTEXT_LIMIT_EXCEEDED
    )
    assert assessment.measurement.tokens > assessment.measurement.limit
    assert runtime.snapshot().active == ()

    decisions = _apply_activation_requests(runtime, ("activate", "skill-1"))

    assert decisions == [{"activated": False, "unavailable": True}]
    assert runtime.snapshot().rejected[0].reason is assessment.rejection_reason


def test_activation_rejects_when_complete_follow_up_exceeds_model_input_limit():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Question"},
    ]
    provider_tools = [{"type": "function", "function": {"name": "lookup"}}]

    with patch(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        return_value=TokenCount(tokens=1_001, source=TokenCountSource.LITELLM),
    ) as measure:
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="activate",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                ),
            ),
            messages=messages,
            provider_tools=provider_tools,
            assistant_content="I will load the payroll procedure.",
        )

    measured_messages, measured_tools, measured_route = measure.call_args.args
    assert measured_tools == provider_tools
    assert measured_route == "openai/gpt-4o"
    assert measured_messages[-1]["content"] == '{"activated": true}'
    assert measured_messages[-2]["content"] == "I will load the payroll procedure."
    snapshot = runtime.snapshot()
    assert snapshot.accepted == ()
    assert snapshot.active == ()
    assert snapshot.rejected[0].reason is (
        SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
    )
    assert "Payroll body" not in str(messages[0]["content"])


@pytest.mark.parametrize(
    ("provider_tokens", "expected_rejection"),
    [
        (1_000, None),
        (
            1_001,
            SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED,
        ),
    ],
    ids=("exact-limit", "overflow"),
)
def test_provider_candidate_assessment_is_exact_and_non_mutating(
    provider_tokens,
    expected_rejection,
):
    candidate = _skill(
        key="skill-1",
        name="Payroll",
        description="Payroll questions",
        position=1,
        instructions="Payroll body",
        initially_active=False,
    )
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(candidate,),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )
    messages = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Minimal non-empty question"},
    ]
    provider_tools = [
        {
            "type": "function",
            "function": {
                "name": "large_mcp_schema",
                "parameters": {"description": "x" * 2_000},
            },
        }
    ]
    snapshot_before = runtime.snapshot()
    messages_before = [message.copy() for message in messages]

    with (
        patch(
            "eneo.completion_models.domain.skill_activation.measure_skill_context",
            wraps=measure_skill_context,
        ) as measure_share,
        patch(
            "eneo.completion_models.domain.skill_activation."
            "measure_provider_input_tokens",
            return_value=TokenCount(
                tokens=provider_tokens,
                source=TokenCountSource.LITELLM,
            ),
        ) as measure,
    ):
        assessments = runtime.assess_provider_payload_candidates(
            frozenset({candidate.binding.skill_id}),
            messages=messages,
            provider_tools=provider_tools,
        )

    assert len(assessments) == 1
    assert measure_share.call_count == 1
    assert assessments[0].rejection_reason is expected_rejection
    assert measure.call_args.args[0][1]["content"] == "Minimal non-empty question"
    assert measure.call_args.args[1] == provider_tools
    assert runtime.snapshot() == snapshot_before
    assert messages == messages_before


def test_model_limit_rejects_oversized_earlier_skill_and_keeps_later_fit():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-a",
                name="Large",
                description="Large procedure",
                position=1,
                instructions="Large body",
                initially_active=False,
            ),
            _skill(
                key="skill-b",
                name="Small",
                description="Small procedure",
                position=2,
                instructions="Small body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Question"},
    ]

    def measure_staged_payload(
        staged_messages: list[dict[str, object]],
        _provider_tools: list[dict[str, object]],
        _model_route: str,
    ) -> TokenCount:
        rendered_prompt = str(staged_messages[0]["content"])
        return TokenCount(
            tokens=1_001 if "Large body" in rendered_prompt else 900,
            source=TokenCountSource.LITELLM,
        )

    with patch(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        side_effect=measure_staged_payload,
    ):
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="activate-large",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-a"}',
                ),
                ProviderToolCall(
                    call_id="activate-small",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-b"}',
                ),
            ),
            messages=messages,
        )

    snapshot = runtime.snapshot()
    assert snapshot.accepted == ("skill-b",)
    assert snapshot.active == ("skill-b",)
    assert snapshot.rejected == (
        SkillActivationRejectionSnapshot(
            activation_key="skill-a",
            reason=SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED,
        ),
    )
    assert "Large body" not in str(messages[0]["content"])
    assert "Small body" in str(messages[0]["content"])


def test_provider_round_bounds_activation_work_and_closes_every_internal_call():
    skills = tuple(
        _skill(
            key=f"skill-{index}",
            name=f"Skill {index}",
            description=f"Procedure {index}",
            position=index,
            instructions=f"Body {index}",
            initially_active=False,
        )
        for index in range(30)
    )
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=skills,
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=MAX_SKILL_ACTIVATIONS_PER_TURN,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Question"},
    ]
    calls = tuple(
        ProviderToolCall(
            call_id=f"activate-{index}",
            name=SKILL_ACTIVATION_TOOL_NAME,
            arguments=json.dumps({"skill_key": f"skill-{index}"}),
        )
        for index in range(30)
    )
    apply_round_batch_sizes: list[int] = []
    original_apply_round = SkillActivationRuntime._apply_round

    def record_apply_round_batch_size(
        staged: SkillActivationRuntime,
        requests: tuple[SkillActivationRequest, ...],
        *,
        forced_rejections: dict[str, SkillActivationRejectionReason],
    ) -> SkillActivationRoundResult:
        apply_round_batch_sizes.append(len(requests))
        return original_apply_round(
            staged,
            requests,
            forced_rejections=forced_rejections,
        )

    with (
        patch.object(
            SkillActivationRuntime,
            "_apply_round",
            new=record_apply_round_batch_size,
        ),
        patch(
            "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
            return_value=TokenCount(tokens=900, source=TokenCountSource.LITELLM),
        ) as measure_provider_payload,
    ):
        runtime.apply_provider_tool_calls(calls=calls, messages=messages)

    tool_messages = [message for message in messages if message.get("role") == "tool"]
    snapshot = runtime.snapshot()
    assert apply_round_batch_sizes
    assert max(apply_round_batch_sizes) <= MAX_SKILL_ACTIVATIONS_PER_TURN
    assert measure_provider_payload.call_count == 1
    assert len(tool_messages) == len(calls)
    assert snapshot.accepted == tuple(
        f"skill-{index}" for index in range(MAX_SKILL_ACTIVATIONS_PER_TURN)
    )
    assert all(
        json.loads(str(message["content"])) == {"activated": False, "unavailable": True}
        for message in tool_messages[MAX_SKILL_ACTIVATIONS_PER_TURN:]
    )
    assert all(
        rejection.reason is SkillActivationRejectionReason.ACTIVATION_LIMIT_EXCEEDED
        for rejection in snapshot.rejected
    )


def test_overflowed_repeat_does_not_record_an_accepted_skill_as_rejected():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll procedure",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=MAX_SKILL_ACTIVATIONS_PER_TURN,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=1_000,
        supports_tool_calling=True,
    )

    with patch(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        return_value=TokenCount(tokens=900, source=TokenCountSource.LITELLM),
    ):
        results = _apply_activation_requests(
            runtime,
            *((f"activate-{index}", "skill-1") for index in range(15)),
        )

    snapshot = runtime.snapshot()
    assert snapshot.accepted == ("skill-1",)
    assert snapshot.repeated == ("skill-1",)
    assert snapshot.rejected == ()
    assert results[0] == {"activated": True}
    assert all(result.get("already_active") is True for result in results[1:10])
    assert all(result.get("already_active") is True for result in results[10:])


def test_activation_rejects_when_complete_follow_up_cannot_be_measured():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Question"},
    ]

    with patch(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        return_value=TokenCount(
            tokens=1,
            source=TokenCountSource.FALLBACK_ESTIMATE,
        ),
    ):
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="activate",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                ),
            ),
            messages=messages,
        )

    snapshot = runtime.snapshot()
    assert snapshot.accepted == ()
    assert snapshot.active == ()
    assert snapshot.rejected[0].reason is (
        SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE
    )
    assert "Payroll body" not in str(messages[0]["content"])


def test_activation_recomposes_accepted_skills_in_saved_binding_order():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-2",
                name="Second",
                description="Second descriptor",
                position=2,
                instructions="Second body",
                initially_active=False,
            ),
            _skill(
                key="skill-1",
                name="First",
                description="First descriptor",
                position=1,
                instructions="First body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )

    decisions = _apply_activation_requests(
        runtime,
        ("call-1", "skill-2"),
        ("call-2", "skill-1"),
    )

    assert decisions == [
        {"activated": True},
        {"activated": True},
    ]
    assert runtime.prompt.index("First body") < runtime.prompt.index("Second body")
    assert runtime.snapshot().accepted == ("skill-2", "skill-1")
    assert runtime.snapshot().active == ("skill-1", "skill-2")


def test_repeated_blocked_unknown_and_limit_decisions_are_closed_per_call():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="First",
                description="First descriptor",
                position=1,
                instructions="First body",
                initially_active=False,
            ),
            _skill(
                key="skill-2",
                name="Second",
                description="Second descriptor",
                position=2,
                instructions="Second body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset({"blocked-skill-1"}),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )

    decisions = _apply_activation_requests(
        runtime,
        ("accepted", "skill-1"),
        ("repeated", "skill-1"),
        ("blocked", "blocked-skill-1"),
        ("unknown", "forged"),
        ("limited", "skill-2"),
    )

    assert decisions[1] == {
        "activated": True,
        "already_active": True,
    }
    assert decisions[2] == {
        "activated": False,
        "unavailable": True,
    }
    assert decisions[3] == decisions[2]
    assert decisions[4] == decisions[2]
    snapshot = runtime.snapshot()
    assert snapshot.repeated == ("skill-1",)
    assert [(item.activation_key, item.reason) for item in snapshot.rejected] == [
        ("blocked-skill-1", SkillActivationRejectionReason.BLOCKED),
        ("forged", SkillActivationRejectionReason.UNKNOWN_KEY),
        ("skill-2", SkillActivationRejectionReason.ACTIVATION_LIMIT_EXCEEDED),
    ]


def test_one_context_overflow_does_not_reject_other_calls_in_the_round():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Too large",
                description="Large optional body",
                position=1,
                instructions="large " * 20_000,
                initially_active=False,
            ),
            _skill(
                key="skill-2",
                name="Fits",
                description="Small optional body",
                position=2,
                instructions="Small body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=2_000,
        supports_tool_calling=True,
    )

    decisions = _apply_activation_requests(
        runtime,
        ("large", "skill-1"),
        ("small", "skill-2"),
    )

    assert decisions[0] == {
        "activated": False,
        "unavailable": True,
    }
    assert decisions[1] == {"activated": True}
    assert runtime.snapshot().active == ("skill-2",)
    assert runtime.snapshot().rejected[0].reason is (
        SkillActivationRejectionReason.CONTEXT_LIMIT_EXCEEDED
    )


def test_rejected_evidence_is_deduplicated_and_bounded():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Optional",
                description="Optional descriptor",
                position=1,
                instructions="Optional body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )

    for index in range(100):
        _apply_activation_requests(
            runtime,
            (f"call-{index}", f"forged-{index}"),
            (f"duplicate-{index}", "same-forged-key"),
        )

    rejected = runtime.snapshot().rejected
    assert len(rejected) == 50
    assert sum(item.activation_key == "same-forged-key" for item in rejected) == 1


def test_accepted_internal_call_preserves_rendered_context_and_defers_external_sibling():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": "Base\n\nKNOWLEDGE_SENTINEL\n\nATTACHMENT_SENTINEL",
        },
        {"role": "user", "content": "Question"},
    ]

    result = runtime.apply_provider_tool_calls(
        calls=(
            ProviderToolCall(
                call_id="activate",
                name=SKILL_ACTIVATION_TOOL_NAME,
                arguments='{"skill_key":"skill-1"}',
            ),
            ProviderToolCall(
                call_id="external",
                name="server__lookup",
                arguments="{}",
            ),
        ),
        messages=messages,
    )

    assert result.external_calls == ()
    assert result.assistant_message_appended is True
    assert "Payroll body" in str(messages[0]["content"])
    assert "KNOWLEDGE_SENTINEL" in str(messages[0]["content"])
    assert "ATTACHMENT_SENTINEL" in str(messages[0]["content"])
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "external",
        "content": (
            '{"deferred": true, "reason": "skill_context_updated", "retryable": true}'
        ),
    }


def test_accepted_internal_call_separates_skill_prompt_from_rendered_context():
    runtime = SkillActivationRuntime.create(
        base_instructions="",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "KNOWLEDGE_SENTINEL"},
        {"role": "user", "content": "Question"},
    ]

    runtime.apply_provider_tool_calls(
        calls=(
            ProviderToolCall(
                call_id="activate",
                name=SKILL_ACTIVATION_TOOL_NAME,
                arguments='{"skill_key":"skill-1"}',
            ),
        ),
        messages=messages,
    )

    assert str(messages[0]["content"]).endswith("Payroll body\n\nKNOWLEDGE_SENTINEL")


def test_accepted_internal_call_rejects_unowned_rendered_prompt():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "DIFFERENT_BASE"},
        {"role": "user", "content": "Question"},
    ]
    snapshot_before = runtime.snapshot()
    messages_before = [message.copy() for message in messages]

    with pytest.raises(SkillPromptOwnershipError, match="frozen Skill prompt"):
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="activate",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                ),
            ),
            messages=messages,
        )

    assert runtime.snapshot() == snapshot_before
    assert messages == messages_before


def test_internal_calls_reject_duplicate_call_ids_before_mutating_runtime():
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
            _skill(
                key="skill-2",
                name="Benefits",
                description="Benefits questions",
                position=2,
                instructions="Benefits body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base"},
        {"role": "user", "content": "Question"},
    ]
    snapshot_before = runtime.snapshot()

    with pytest.raises(InvalidSkillToolCallError, match="invalid tool call"):
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="duplicate",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                ),
                ProviderToolCall(
                    call_id="duplicate",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-2"}',
                ),
            ),
            messages=messages,
        )

    assert runtime.snapshot() == snapshot_before


def test_rejected_internal_call_keeps_external_sibling_dispatchable():
    runtime = SkillActivationRuntime.create(
        base_instructions="",
        skills=(
            _skill(
                key="skill-1",
                name="Payroll",
                description="Payroll questions",
                position=1,
                instructions="Payroll body",
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=1,
        context_share_percent=100,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    external = ProviderToolCall(
        call_id="external",
        name="server__lookup",
        arguments="{}",
    )
    messages: list[dict[str, object]] = [{"role": "user", "content": "Question"}]

    result = runtime.apply_provider_tool_calls(
        calls=(
            ProviderToolCall(
                call_id="invalid",
                name=SKILL_ACTIVATION_TOOL_NAME,
                arguments="{",
            ),
            external,
        ),
        messages=messages,
    )

    assert result.external_calls == (external,)
    assert result.assistant_message_appended is True
    assert messages[0]["role"] == "user"
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "invalid",
        "content": '{"activated": false, "unavailable": true}',
    }
