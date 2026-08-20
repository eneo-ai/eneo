from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    _retryable_architecture_failure_code,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    apply_template_attachment_contract,
)
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
from eneo.flows.variable_resolver import FlowVariableResolver


def _template_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Template flow",
        form_fields=[
            FormFieldSpec(
                name="case_id",
                type="text",
                label="Case ID",
                required=False,
            )
        ],
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Draft",
                assistant_spec=AssistantSpec(instructions="Draft text."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract fields."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "customer": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                            "additionalProperties": False,
                        }
                    },
                    "required": ["customer"],
                    "additionalProperties": False,
                },
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Fill",
                assistant_spec=AssistantSpec(instructions="Fill the template."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ),
        ],
    )


def test_contract_is_complete_before_approval_and_hashing() -> None:
    spec = _template_spec()

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=(
            "case_id",
            "flow_input.reference_number",
            "datum",
            "step_a.output.text",
            "step_b.output.structured.customer.name",
        ),
    )

    fields = {field.name: field for field in contracted.form_fields or []}
    assert fields["case_id"].label == "Case ID"
    assert fields["case_id"].required is True
    assert fields["reference_number"].required is True
    assert contracted.steps[-1].output_config == {
        "bindings": {
            "case_id": "{{ flow_input.case_id }}",
            "flow_input.reference_number": "{{ flow_input.reference_number }}",
            "datum": "{{ datum }}",
            "step_a.output.text": "{{ step_a.output.text }}",
            "step_b.output.structured.customer.name": (
                "{{ step_b.output.structured.customer.name }}"
            ),
        }
    }
    assert contracted.spec_hash() != spec.spec_hash()

    for unresolved_placeholder in (
        "step_c.output.text",
        "step_d.output.text",
    ):
        with pytest.raises(AIBuilderArchitectureError) as exc_info:
            apply_template_attachment_contract(
                spec,
                selected_template_count=1,
                placeholders=(unresolved_placeholder,),
            )
        assert exc_info.value.log_context["failure_code"] == (
            "template_placeholder_unresolved"
        )


def test_contract_preserves_exact_placeholder_whitespace() -> None:
    contracted = apply_template_attachment_contract(
        _template_spec(),
        selected_template_count=1,
        placeholders=("customer   name", "customer   name"),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "customer   name": "{{ step_b.output.structured.customer.name }}",
        }
    }


def test_contract_refuses_template_without_successful_byte_inspection() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(),
            selected_template_count=1,
            placeholders=None,
        )

    assert exc_info.value.log_context["failure_code"] == (
        "template_attachment_unreadable"
    )
    assert _retryable_architecture_failure_code(exc_info.value) is None


def test_contract_requires_audio_and_accepts_runtime_injected_transcription_bindings() -> (
    None
):
    spec = _template_spec()
    first = spec.steps[0].model_copy(update={"input_type": InputType.AUDIO})
    spec = spec.model_copy(update={"steps": [first, *spec.steps[1:]]})
    placeholders = (
        "transkribering",
        "flow_input.transkribering",
        "flow.input.transkribering",
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=placeholders,
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            placeholder: "{{ " + placeholder + " }}" for placeholder in placeholders
        }
    }
    runtime_input = build_runtime_input_config(contracted.steps[0].input_config)
    assert runtime_input.enabled is True
    assert runtime_input.required is True
    assert runtime_input.input_format == InputType.AUDIO.value
    assert contracted.spec_hash() != spec.spec_hash()
    payload = FlowRunInputEnvelopePatch.transcription(
        transcript="Verified transcript",
    ).apply_to({})
    resolver = FlowVariableResolver()
    context = resolver.build_context(payload, [])
    for binding in contracted.steps[-1].output_config["bindings"].values():
        assert resolver.interpolate(binding, context) == "Verified transcript"


def test_contract_accepts_previous_step_alias_only_for_text_predecessor() -> None:
    spec = _template_spec().model_copy(
        update={"steps": [_template_spec().steps[0], _template_spec().steps[-1]]}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("föregående_steg",),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {"föregående_steg": "{{ föregående_steg }}"}
    }


@pytest.mark.parametrize(
    "placeholder",
    [
        "step_input.text",
        "flow.foo",
        "flow_input.case_id.nested",
        "indata_text",
        "indata_json",
        "indata_json.case_id",
        "flow_input.text",
        "flow_input.json",
        "flow_input.structured",
        "flow_input.transcription",
        "flow_input.transcript",
        "flow_input.transcribed_text",
        "step_c.output.text",
        "step_b.output.structured.unknown",
        "step_b.status",
    ],
)
def test_contract_rejects_bindings_template_runtime_cannot_prove(
    placeholder: str,
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(),
            selected_template_count=1,
            placeholders=(placeholder,),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "template_placeholder_unresolved"
    )


def _prepared_fields_spec() -> FlowDraftSpecCore:
    """A template flow whose preparation step declares Swedish content fields."""

    spec = _template_spec()
    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "arendet": {"type": "string"},
                    "sections_arendet_text": {"type": "string"},
                    "diarienummer": {"type": "string"},
                    "case_id": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "arendet",
                    "sections_arendet_text",
                    "diarienummer",
                    "case_id",
                    "metadata",
                ],
                "additionalProperties": False,
            }
        }
    )
    return spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})


def test_contract_binds_human_named_placeholders_to_prepared_fields() -> None:
    contracted = apply_template_attachment_contract(
        _prepared_fields_spec(),
        selected_template_count=1,
        placeholders=("Ärendet", "sections.ärendet.text", "diarienummer"),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "Ärendet": "{{ step_b.output.structured.arendet }}",
            "sections.ärendet.text": (
                "{{ step_b.output.structured.sections_arendet_text }}"
            ),
            "diarienummer": "{{ step_b.output.structured.diarienummer }}",
        }
    }
    field_names = {field.name for field in contracted.form_fields or ()}
    assert "Ärendet" not in field_names
    assert "diarienummer" not in field_names


def test_contract_binds_nested_placeholder_to_declared_string_leaf() -> None:
    spec = _template_spec()
    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {
                            "ärendet": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                                "additionalProperties": False,
                            }
                        },
                        "required": ["ärendet"],
                        "additionalProperties": False,
                    }
                },
                "required": ["sections"],
                "additionalProperties": False,
            }
        }
    )
    spec = spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("sections.ärendet.text",),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "sections.ärendet.text": (
                "{{ step_b.output.structured.sections.ärendet.text }}"
            )
        }
    }


def test_contract_drops_unused_text_step_before_template_fill() -> None:
    spec = _template_spec()
    unused_text_step = StepSpec(
        plan_step_ref="step_unused",
        name="Fill the template",
        assistant_spec=AssistantSpec(instructions="Write a final letter."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.TEXT,
    )
    spec = spec.model_copy(
        update={
            "steps": [
                spec.steps[0],
                spec.steps[1],
                unused_text_step,
                spec.steps[2].model_copy(
                    update={
                        "input_bindings": {
                            "source_refs": [
                                {
                                    "step_ref": "step_unused",
                                    "output": "text",
                                }
                            ]
                        }
                    }
                ),
            ]
        }
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("customer.name",),
    )

    assert [step.plan_step_ref for step in contracted.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert contracted.steps[-1].output_config == {
        "bindings": {"customer.name": "{{ step_b.output.structured.customer.name }}"}
    }
    assert contracted.steps[-1].input_bindings is None


def test_contract_keeps_text_step_referenced_by_template() -> None:
    spec = _template_spec()
    referenced_text_step = spec.steps[0].model_copy(
        update={"plan_step_ref": "step_letter", "name": "Write the letter"}
    )
    spec = spec.model_copy(
        update={"steps": [spec.steps[1], referenced_text_step, spec.steps[2]]}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("föregående_steg",),
    )

    assert [step.plan_step_ref for step in contracted.steps] == [
        "step_b",
        "step_letter",
        "step_c",
    ]
    assert contracted.steps[-1].output_config == {
        "bindings": {"föregående_steg": "{{ föregående_steg }}"}
    }


def test_contract_prefers_declared_form_field_over_prepared_field() -> None:
    contracted = apply_template_attachment_contract(
        _prepared_fields_spec(),
        selected_template_count=1,
        placeholders=("case_id",),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {"case_id": "{{ flow_input.case_id }}"}
    }


def test_contract_prefers_latest_preparation_step_for_prepared_fields() -> None:
    spec = _prepared_fields_spec()
    refine = spec.steps[1].model_copy(
        update={
            "plan_step_ref": "step_refine",
            "name": "Refine",
            "output_contract": {
                "type": "object",
                "properties": {"arendet": {"type": "string"}},
                "required": ["arendet"],
                "additionalProperties": False,
            },
        }
    )
    spec = spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], refine, spec.steps[2]]}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("ärendet",),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {"ärendet": "{{ step_refine.output.structured.arendet }}"}
    }


def test_contract_ignores_non_string_prepared_fields() -> None:
    contracted = apply_template_attachment_contract(
        _prepared_fields_spec(),
        selected_template_count=1,
        placeholders=("metadata",),
    )

    # The object-typed prepared field is not bindable content, so the
    # placeholder falls back to a required runtime form field.
    assert contracted.steps[-1].output_config == {
        "bindings": {"metadata": "{{ flow_input.metadata }}"}
    }
    fields = {field.name: field for field in contracted.form_fields or ()}
    assert fields["metadata"].required is True


@pytest.mark.parametrize("selected_template_count", [0, 2])
def test_contract_requires_exactly_one_selected_template(
    selected_template_count: int,
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(),
            selected_template_count=selected_template_count,
            placeholders=(),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "template_attachment_selection_invalid"
    )
