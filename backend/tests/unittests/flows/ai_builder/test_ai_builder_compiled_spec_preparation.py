from __future__ import annotations

from unittest.mock import MagicMock, patch

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

_DEFAULT_HELPER_INPUT_BINDINGS = object()


def _make_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Testflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(
                    instructions="Analysera underlaget.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )


def _duplicate_step_name_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Duplicate step names",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Förbered DOCX-innehåll",
                assistant_spec=AssistantSpec(instructions="Prepare report text."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="förbered docx-innehåll",
                assistant_spec=AssistantSpec(instructions="Prepare final document text."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _json_helper_before_text_terminal_spec(
    *,
    helper_input_source: InputSource = InputSource.PREVIOUS_STEP,
    helper_input_bindings: dict[str, object] | None | object = (
        _DEFAULT_HELPER_INPUT_BINDINGS
    ),
    terminal_input_source: InputSource = InputSource.PREVIOUS_STEP,
    terminal_output_mode: OutputMode = OutputMode.PASS_THROUGH,
) -> FlowDraftSpecCore:
    if helper_input_bindings is _DEFAULT_HELPER_INPUT_BINDINGS:
        helper_input_bindings = {"question": "{{ step_a.output.structured }}"}

    return FlowDraftSpecCore(
        flow_name="Structured comparison",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract source facts",
                assistant_spec=AssistantSpec(
                    instructions="Extract structured facts from the source.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Prepare JSON result",
                assistant_spec=AssistantSpec(
                    instructions="Create the final structured JSON object.",
                ),
                input_source=helper_input_source,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                input_bindings=helper_input_bindings,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Create final result",
                assistant_spec=AssistantSpec(
                    instructions="Return the final result.",
                ),
                input_source=terminal_input_source,
                input_type=InputType.JSON,
                output_mode=terminal_output_mode,
                output_type=OutputType.TEXT,
                input_bindings={"question": "{{ step_b.output.structured }}"},
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def test_prepare_compiled_spec_for_session_merges_session_validation_errors() -> None:
    validation = SpecValidationResult()
    session_validation = MagicMock(
        errors=[
            MagicMock(
                step_ref="step_a",
                code="session_error",
                message="Session-only validation failed.",
            )
        ]
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=validation,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=session_validation,
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_make_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
        )

    assert result.failure_feedback is None
    assert result.spec is not None
    assert result.validation is validation
    assert any(error.code == "session_error" for error in validation.errors)


def test_prepare_compiled_spec_for_session_returns_resource_failure_feedback() -> None:
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.canonicalize_flow_spec_resources",
            return_value=(_make_spec(), ["missing model ref"]),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.format_resource_resolution_feedback",
            return_value="resource issue",
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_make_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=MagicMock(),
            valid_existing_step_refs=None,
        )

    assert result.spec is None
    assert result.validation is None
    assert result.failure_feedback == "resource issue"


def test_prepare_compiled_spec_for_session_expands_mcp_server_refs_to_tools() -> None:
    spec = _make_spec()
    spec = spec.model_copy(
        update={
            "steps": [
                spec.steps[0].model_copy(
                    update={
                        "assistant_spec": spec.steps[0].assistant_spec.model_copy(
                            update={"mcp_server_refs": ["Time MCP"]}
                        )
                    }
                )
            ]
        }
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-time",
                "name": "Time MCP",
                "tools": [
                    {"id": "tool-current-time", "name": "get_current_time"},
                    {"id": "tool-convert-time", "name": "convert_time"},
                ],
            }
        ],
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            valid_existing_step_refs=None,
        )

    assert result.spec is not None
    assistant_spec = result.spec.steps[0].assistant_spec
    assert assistant_spec.mcp_server_refs == ["server-time"]
    assert assistant_spec.mcp_tool_refs == ["tool-current-time", "tool-convert-time"]


def test_prepare_compiled_spec_normalizes_output_contract_prompt_metadata() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Structured extraction",
        flow_description="Extract structured meeting facts.",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract meeting facts",
                assistant_spec=AssistantSpec(
                    instructions="Extract the important meeting facts.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "meeting_context": {"type": "string"},
                        "participants": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["meeting_context", "participants"],
                },
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )

    result = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        valid_existing_step_refs=None,
    )

    assert result.spec is not None
    assert result.validation is not None
    prepared_step = result.spec.steps[0]
    instructions = prepared_step.assistant_spec.instructions
    assert "meeting_context" in instructions
    assert "participants" in instructions
    contract = prepared_step.output_contract
    assert contract is not None
    properties = contract["properties"]
    assert isinstance(properties, dict)
    meeting_context = properties["meeting_context"]
    participants = properties["participants"]
    assert isinstance(meeting_context, dict)
    assert isinstance(participants, dict)
    assert "description" not in meeting_context
    assert "description" not in participants
    warning_codes = {warning.code for warning in result.validation.warnings}
    assert "contract_instruction_mismatch" not in warning_codes


def test_prepare_compiled_spec_for_session_rejects_terminal_output_type_drift() -> None:
    spec = _make_spec()

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
            terminal_output_type=OutputType.PDF,
        )

    assert result.validation is not None
    assert not result.validation.valid
    assert result.validation.errors[0].code == "terminal_output_type_mismatch"


def test_prepare_compiled_spec_for_session_promotes_terminal_text_artifact_contract() -> (
    None
):
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_make_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
            terminal_output_type=OutputType.DOCX,
        )

    assert result.spec is not None
    assert result.validation is not None
    assert result.validation.valid
    terminal = result.spec.steps[-1]
    assert terminal.output_type == OutputType.DOCX
    assert "Create the final DOCX file" in terminal.assistant_spec.instructions


def test_prepare_compiled_spec_for_session_disambiguates_duplicate_step_names() -> None:
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_duplicate_step_name_spec(),
            target_kind=TargetKind.EDIT,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=[],
        )

    assert result.spec is not None
    assert result.validation is not None
    assert result.validation.valid
    assert [step.name for step in result.spec.steps] == [
        "Förbered DOCX-innehåll",
        "förbered docx-innehåll (2)",
    ]


def test_prepare_compiled_spec_for_session_folds_json_helper_before_text_terminal() -> (
    None
):
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_json_helper_before_text_terminal_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
            terminal_output_type=OutputType.JSON,
        )

    assert result.spec is not None
    assert result.validation is not None
    assert result.validation.valid
    assert [step.plan_step_ref for step in result.spec.steps] == ["step_a", "step_c"]
    assert result.spec.steps[-1].output_type == OutputType.JSON


def test_prepare_compiled_spec_for_session_rejects_json_all_previous_text_terminal() -> (
    None
):
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_json_helper_before_text_terminal_spec(
                terminal_input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
            terminal_output_type=OutputType.JSON,
        )

    assert result.spec is not None
    assert result.validation is not None
    assert not result.validation.valid
    assert [step.plan_step_ref for step in result.spec.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert result.spec.steps[-1].output_type == OutputType.TEXT
    assert result.validation.errors[-1].code == "terminal_output_type_mismatch"


def test_prepare_compiled_spec_for_session_rejects_unfoldable_json_text_terminal() -> (
    None
):
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_compiled_spec_for_session",
            side_effect=lambda spec, target_kind: spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_compiled_spec_for_session",
            return_value=MagicMock(errors=[]),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_json_helper_before_text_terminal_spec(
                helper_input_source=InputSource.ALL_PREVIOUS_STEPS,
                helper_input_bindings=None,
                terminal_input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            valid_existing_step_refs=None,
            terminal_output_type=OutputType.JSON,
        )

    assert result.spec is not None
    assert result.validation is not None
    assert not result.validation.valid
    assert result.validation.errors[-1].code == "terminal_output_type_mismatch"
