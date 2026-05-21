from __future__ import annotations

from intric.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_session_spec_validator import (
    normalize_compiled_spec_for_session,
    validate_compiled_spec_for_session,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)


def _make_spec(*, existing_step_ref: str | None) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Testflöde",
        flow_description="Beskrivning",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=existing_step_ref,
                name="Steg A",
                assistant_spec=AssistantSpec(instructions="Gör jobbet."),
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def test_create_mode_rejects_any_existing_step_ref() -> None:
    result = validate_compiled_spec_for_session(
        _make_spec(existing_step_ref="step_a"),
        target_kind=TargetKind.CREATE,
        valid_existing_step_refs=None,
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_create_mode_normalization_strips_existing_step_ref() -> None:
    normalized = normalize_compiled_spec_for_session(
        _make_spec(existing_step_ref="step_a"),
        target_kind=TargetKind.CREATE,
    )

    assert normalized.steps[0].existing_step_ref is None


def test_edit_mode_rejects_non_existing_step_alias_format() -> None:
    result = validate_compiled_spec_for_session(
        _make_spec(existing_step_ref="step_a"),
        target_kind=TargetKind.EDIT,
        valid_existing_step_refs=["existing_step_1"],
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_edit_mode_rejects_unknown_existing_step_ref() -> None:
    result = validate_compiled_spec_for_session(
        _make_spec(existing_step_ref="existing_step_99"),
        target_kind=TargetKind.EDIT,
        valid_existing_step_refs=["existing_step_1"],
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"
