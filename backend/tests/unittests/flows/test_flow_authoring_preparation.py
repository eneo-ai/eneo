from __future__ import annotations

from intric.flows.application.flow_authoring_preparation import (
    validate_prepared_flow_authoring_spec,
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


def test_create_mode_rejects_any_existing_step_ref() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec("step_a"),
        target_kind="create",
        valid_existing_step_refs=None,
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_edit_mode_rejects_non_existing_step_alias_format() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec("step_a"),
        target_kind="edit",
        valid_existing_step_refs=["existing_step_1"],
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_edit_mode_rejects_unknown_existing_step_ref() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec("existing_step_99"),
        target_kind="edit",
        valid_existing_step_refs=["existing_step_1"],
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_edit_mode_rejects_duplicate_existing_step_ref() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec("existing_step_1", "existing_step_1"),
        target_kind="edit",
        valid_existing_step_refs=["existing_step_1"],
    )

    assert not result.valid
    assert result.errors[0].code == "invalid_existing_step_ref"


def test_terminal_output_type_mismatch_is_reported_when_requested() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec(None, output_types=[OutputType.TEXT]),
        target_kind="create",
        valid_existing_step_refs=None,
        terminal_output_type=OutputType.PDF,
    )

    assert not result.valid
    assert result.errors[0].code == "terminal_output_type_mismatch"


def test_terminal_output_type_is_not_required_without_request_context() -> None:
    result = validate_prepared_flow_authoring_spec(
        spec=_make_spec(None, output_types=[OutputType.TEXT]),
        target_kind="create",
        valid_existing_step_refs=None,
    )

    assert result.valid


def _make_spec(
    *existing_step_refs: str | None,
    output_types: list[OutputType] | None = None,
) -> FlowDraftSpecCore:
    outputs = output_types or [OutputType.TEXT for _ in existing_step_refs]
    return FlowDraftSpecCore(
        flow_name="Test flow",
        flow_description="Description",
        steps=[
            StepSpec(
                plan_step_ref=f"step_{index}",
                existing_step_ref=existing_step_ref,
                name=f"Step {index}",
                assistant_spec=AssistantSpec(instructions="Do the work."),
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=outputs[index - 1],
            )
            for index, existing_step_ref in enumerate(existing_step_refs, start=1)
        ],
    )
