from __future__ import annotations

from unittest.mock import MagicMock, patch

from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding


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
                assistant_spec=AssistantSpec(
                    instructions="Prepare final document text."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _json_helper_before_text_terminal_spec() -> FlowDraftSpecCore:
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
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                input_bindings={"question": "{{ step_a.output.structured }}"},
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Create final result",
                assistant_spec=AssistantSpec(
                    instructions="Return the final result.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                input_bindings={"question": "{{ step_b.output.structured }}"},
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _multi_step_fan_in_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Explicit synthesis",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract A",
                assistant_spec=AssistantSpec(instructions="Extract source A."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract B",
                assistant_spec=AssistantSpec(instructions="Extract source B."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Compare extracts",
                assistant_spec=AssistantSpec(instructions="Compare both extracts."),
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                input_bindings={
                    "question": "{{ step_a.output.text }}\n\n{{ step_b.output.text }}"
                },
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _pdf_helper_before_text_terminal_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Employee review",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analyze conversation",
                assistant_spec=AssistantSpec(
                    instructions="Analyze the employee review conversation.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Generate PDF helper",
                assistant_spec=AssistantSpec(
                    instructions="Render the analysis as a PDF.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.PDF,
                input_bindings={"question": "{{ step_a.output.structured }}"},
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Create final result",
                assistant_spec=AssistantSpec(
                    instructions="Return the final review document.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                input_bindings={"question": "{{ step_b.output.text }}"},
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _source_material_docx_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Mötesprotokoll från ljud",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera ljud",
                assistant_spec=AssistantSpec(
                    instructions="Transcribe the uploaded meeting audio.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Strukturera transkription",
                assistant_spec=AssistantSpec(
                    instructions="Extract structured decisions from the transcript.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Identifiera mötesmetadata",
                assistant_spec=AssistantSpec(
                    instructions="Identify agenda and meeting metadata.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                input_contract={
                    "type": "object",
                    "properties": {"agenda": {"type": "array"}},
                },
                mcp_policy=MCPPolicy.INHERIT,
            ),
            StepSpec(
                plan_step_ref="step_d",
                name="Skapa DOCX",
                assistant_spec=AssistantSpec(
                    instructions="Create the final meeting protocol.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.DOCX,
                input_contract={
                    "type": "object",
                    "properties": {"metadata": {"type": "object"}},
                },
                mcp_policy=MCPPolicy.INHERIT,
            ),
        ],
    )


def _assert_prepared_spec_compiles_with_shared_compiler(
    spec: FlowDraftSpecCore,
) -> None:
    shared_changeset = compile_flow_draft_changeset(spec, current_flow=None)
    assert len(shared_changeset.compiled_steps) == len(spec.steps)


def _assert_prepared_spec_is_apply_normalization_fixed_point(
    spec: FlowDraftSpecCore,
) -> None:
    normalized, normalization_changes = normalize_ai_builder_spec(spec)

    assert normalized == spec
    assert normalization_changes == []
    _assert_prepared_spec_compiles_with_shared_compiler(spec)


def _prepare_valid_spec(
    spec: FlowDraftSpecCore,
    *,
    target_kind: TargetKind = TargetKind.CREATE,
    terminal_output_type: OutputType | None = None,
) -> FlowDraftSpecCore:
    result = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=target_kind,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        terminal_output_type=terminal_output_type,
    )

    assert result.spec is not None
    assert result.validation is not None
    assert result.validation.valid
    return result.spec


def test_prepare_compiled_spec_for_session_returns_resource_failure_feedback() -> None:
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.canonicalize_flow_spec_resources",
            return_value=(_make_spec(), ["missing model ref"]),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.format_resource_resolution_feedback",
            return_value="resource issue",
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_make_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=MagicMock(),
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
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
        )

    assert result.spec is not None
    assistant_spec = result.spec.steps[0].assistant_spec
    assert assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-get-current-time",
        "mcp_tool.time-mcp-convert-time",
    ]


def test_prepared_simple_create_spec_is_apply_normalization_fixed_point() -> None:
    spec = _prepare_valid_spec(_make_spec())

    _assert_prepared_spec_is_apply_normalization_fixed_point(spec)


def test_prepared_explicit_multi_step_fan_in_is_apply_normalization_fixed_point() -> (
    None
):
    spec = _prepare_valid_spec(_multi_step_fan_in_spec())

    _assert_prepared_spec_is_apply_normalization_fixed_point(spec)


def test_prepare_compiled_spec_for_session_rejects_terminal_output_type_drift() -> None:
    spec = _make_spec()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=lambda spec, **_kwargs: (spec, []),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            terminal_output_type=OutputType.PDF,
        )

    assert result.validation is not None
    assert not result.validation.valid
    assert result.validation.errors[0].code == "terminal_output_type_mismatch"


def test_prepare_compiled_spec_for_session_rejects_terminal_text_artifact_mismatch() -> (
    None
):
    result = prepare_compiled_spec_for_session(
        spec=_make_spec(),
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        terminal_output_type=OutputType.DOCX,
    )

    assert result.spec is not None
    assert result.validation is not None
    assert not result.validation.valid
    terminal = result.spec.steps[-1]
    assert terminal.output_type == OutputType.TEXT
    assert result.validation.errors[-1].code == "terminal_output_type_mismatch"


def test_prepare_compiled_spec_for_session_rejects_pdf_helper_before_text_terminal() -> (
    None
):
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_pdf_helper_before_text_terminal_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            terminal_output_type=OutputType.PDF,
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


def test_prepare_compiled_spec_for_session_disambiguates_duplicate_step_names() -> None:
    result = prepare_compiled_spec_for_session(
        spec=_duplicate_step_name_spec(),
        target_kind=TargetKind.EDIT,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
    )

    assert result.spec is not None
    assert result.validation is not None
    assert result.validation.valid
    assert [step.name for step in result.spec.steps] == [
        "Förbered DOCX-innehåll",
        "förbered docx-innehåll (2)",
    ]


def test_prepared_edit_duplicate_names_are_apply_compile_stable() -> None:
    spec = _prepare_valid_spec(
        _duplicate_step_name_spec(),
        target_kind=TargetKind.EDIT,
    )

    _assert_prepared_spec_is_apply_normalization_fixed_point(spec)


def test_prepare_compiled_spec_for_session_rejects_json_helper_before_text_terminal() -> (
    None
):
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
    ):
        result = prepare_compiled_spec_for_session(
            spec=_json_helper_before_text_terminal_spec(),
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
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


def test_prepare_compiled_spec_for_session_rejects_source_material_docx_pass_through() -> (
    None
):
    result = prepare_compiled_spec_for_session(
        spec=_source_material_docx_spec(),
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        terminal_output_type=OutputType.DOCX,
    )

    assert result.spec is not None
    assert result.validation is not None
    assert not result.validation.valid
    assert result.spec.steps[2].input_bindings == {
        "source_refs": [
            {"step_ref": "step_b", "output": "structured"},
            {"step_ref": "step_a", "output": "text", "label": "Källmaterial"},
        ]
    }
    assert effective_question_binding(result.spec.steps[2].input_bindings) == (
        "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert result.spec.steps[3].input_bindings == {
        "source_refs": [
            {"step_ref": "step_c", "output": "structured"},
            {"step_ref": "step_a", "output": "text", "label": "Källmaterial"},
        ]
    }
    assert result.spec.steps[3].output_mode == OutputMode.PASS_THROUGH
    assert effective_question_binding(result.spec.steps[3].input_bindings) == (
        "{{ step_c.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert result.validation.errors[0].code == "flow_step_invalid"
