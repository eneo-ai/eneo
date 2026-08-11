from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


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
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract B",
                assistant_spec=AssistantSpec(instructions="Extract source B."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
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
            ),
        ],
    )


def _assembly_document_pdf_spec() -> FlowDraftSpecCore:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys till PDF",
            "plan_rationale": (
                "Läs dokument, skriv rapportinnehåll och leverera som PDF."
            ),
            "steps": [
                {
                    "name": "Identifiera dokumentens innehåll",
                    "instructions": (
                        "Läs varje inskickat dokument och avgör vad det är för "
                        "typ av dokument, vilket ämne det handlar om, kategori, "
                        "datum, författare och slutsatser."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": (
                                "En post per dokument i körningen med de uppgifter "
                                "som ska användas i rapporten."
                            ),
                        }
                    ],
                },
                {
                    "name": "Skriv rapportinnehåll",
                    "instructions": (
                        "Använd den extraherade informationen för att skriva den "
                        "fullständiga rapporttexten för PDF:en."
                    ),
                    "output_type": "text",
                },
                {
                    "name": "Skapa PDF-rapport",
                    "instructions": (
                        "Omvandla den färdiga rapporttexten till en professionell PDF."
                    ),
                    "output_type": "text",
                },
            ],
        }
    )
    return compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            aggregation_intent=cast(AggregationIntent, "linear"),
            ui_language="sv",
        ),
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


def test_prepare_create_spec_does_not_run_transition_normalizer() -> None:
    spec = _make_spec()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
            side_effect=AssertionError("create output must not be post-normalized"),
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
        )

    assert result.spec == spec
    assert result.validation is not None
    assert result.validation.valid


def test_prepare_create_spec_rejects_unknown_flow_input_key() -> None:
    spec = _make_spec()
    step = spec.steps[0]
    spec = spec.model_copy(
        update={
            "steps": [
                step.model_copy(
                    update={
                        "assistant_spec": step.assistant_spec.model_copy(
                            update={
                                "instructions": "Use {{ flow_input.case_identifier }}."
                            }
                        )
                    }
                )
            ]
        }
    )

    result = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
    )

    assert result.validation is not None
    assert not result.validation.valid
    assert {error.code for error in result.validation.errors} == {
        "invalid_runtime_variable_path"
    }


def test_prepare_compiled_spec_for_session_returns_resource_failure_feedback() -> None:
    with (
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


def test_prepared_simple_create_spec_is_apply_normalization_fixed_point() -> None:
    spec = _prepare_valid_spec(_make_spec())

    _assert_prepared_spec_is_apply_normalization_fixed_point(spec)


def test_prepared_explicit_multi_step_fan_in_is_apply_normalization_fixed_point() -> (
    None
):
    spec = _prepare_valid_spec(_multi_step_fan_in_spec())

    _assert_prepared_spec_is_apply_normalization_fixed_point(spec)


def test_prepared_assembly_document_pdf_spec_is_normalization_fixed_point() -> None:
    compiled = _assembly_document_pdf_spec()

    prepared = _prepare_valid_spec(
        compiled,
        terminal_output_type=OutputType.PDF,
    )
    normalized, normalization_changes = normalize_ai_builder_spec(
        prepared,
        terminal_output_type=OutputType.PDF,
        ui_language="sv",
    )

    assert prepared == compiled
    assert normalized == prepared
    assert normalization_changes == []
    assert [step.output_type for step in prepared.steps] == [
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.PDF,
    ]
    assert prepared.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    _assert_prepared_spec_compiles_with_shared_compiler(prepared)


def test_create_terminal_output_drift_is_a_typed_compiler_defect() -> None:
    spec = _make_spec()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.validate_spec",
            return_value=SpecValidationResult(),
        ),
        pytest.raises(AIBuilderArchitectureError) as exc_info,
    ):
        prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            terminal_output_type=OutputType.PDF,
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context == {
        "failure_code": "terminal_output_type_mismatch",
        "reason": "terminal_output_type_mismatch",
        "expected_output_type": "pdf",
        "actual_output_type": "text",
        "step_ref": "step_a",
    }


def test_edit_terminal_output_drift_remains_validation_feedback() -> None:
    result = prepare_compiled_spec_for_session(
        spec=_make_spec(),
        target_kind=TargetKind.EDIT,
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


def test_prepare_compiled_spec_for_session_rejects_text_document_pass_through() -> None:
    spec = _make_spec()
    spec = spec.model_copy(
        update={
            "steps": [spec.steps[0].model_copy(update={"output_type": OutputType.DOCX})]
        }
    )

    result = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        terminal_output_type=OutputType.DOCX,
    )

    assert result.spec is not None
    assert result.validation is not None
    assert not result.validation.valid
    assert result.validation.errors[0].code == "flow_step_invalid"
