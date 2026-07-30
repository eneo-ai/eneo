from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    apply_template_attachment_contract,
)
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
from eneo.flows.runtime_input import build_runtime_input_config
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


def test_contract_preserves_exact_placeholder_whitespace() -> None:
    contracted = apply_template_attachment_contract(
        _template_spec(),
        selected_template_count=1,
        placeholders=("customer   name", "customer   name"),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "customer   name": "{{ flow_input.customer name }}",
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
