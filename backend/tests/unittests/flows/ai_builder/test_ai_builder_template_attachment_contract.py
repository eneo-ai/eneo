from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import jsonschema
import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_output_contract,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import user_action_answer
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_NAMES,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    MAX_TEMPLATE_MATERIALIZED_PATHS,
    apply_template_attachment_contract,
)
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.step_output import inline_transcript
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
    metadata_json_from_authoring_form_fields,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
from eneo.flows.flow_validators import (
    collect_step_graph_issues,
    template_bound_path_ok,
)
from eneo.flows.input_binding_contract_rules import (
    derive_structured_projection_contract,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from tests.unittests.flows.schema_witness_support import (
    all_plain,
    local_listener,
    witness,
)


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
    # A declared text field keeps its own requirement (empty text renders);
    # a placeholder naming a run input is a required run field.
    assert fields["case_id"].required is False
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
    assert exc_info.value.repair_disposition == "user_action"


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
        transcript=inline_transcript(
            text="Verified transcript",
            source_step_id=uuid4(),
            source_attempt_no=1,
        ),
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


def test_contract_binds_required_nullable_nested_string_leaf() -> None:
    spec = _template_spec()
    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {
                            "decision": {
                                "type": "object",
                                "properties": {"note": {"type": ["string", "null"]}},
                                "required": ["note"],
                                "additionalProperties": False,
                            }
                        },
                        "required": ["decision"],
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
        placeholders=("sections.decision.note",),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "sections.decision.note": (
                "{{ step_b.output.structured.sections.decision.note }}"
            )
        }
    }
    # The fill step rejects null, so the field it reads is text that may be "".
    contract = contracted.steps[1].output_contract
    assert contract is not None
    note = contract["properties"]["sections"]["properties"]["decision"]["properties"][
        "note"
    ]
    assert note == {"type": "string"}


def test_contract_promotes_optional_nested_string_path_required_by_template() -> None:
    spec = _template_spec()
    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {
                            "decision": {
                                "type": "object",
                                "properties": {"note": {"type": "string"}},
                                "required": [],
                                "additionalProperties": False,
                            }
                        },
                        "required": [],
                        "additionalProperties": False,
                    }
                },
                "required": [],
                "additionalProperties": False,
            }
        }
    )
    spec = spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("sections.decision.note",),
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["required"] == ["sections"]
    sections = contract["properties"]["sections"]
    assert sections["required"] == ["decision"]
    assert sections["properties"]["decision"]["required"] == ["note"]
    assert contracted.steps[-1].output_config == {
        "bindings": {
            "sections.decision.note": (
                "{{ step_b.output.structured.sections.decision.note }}"
            )
        }
    }


def test_contract_materializes_missing_nested_placeholder_on_json_preparation() -> None:
    spec = _template_spec()

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=(
            "customer.name",
            "arende.diarienummer",
            "arende.plats",
        ),
    )

    preparation = contracted.steps[1]
    assert preparation.output_contract == {
        "type": "object",
        "properties": {
            "customer": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            "arende": {
                "type": "object",
                "properties": {
                    "diarienummer": {
                        "type": "string",
                        "description": (
                            "Value for DOCX template placeholder 'arende.diarienummer'."
                        ),
                    },
                    "plats": {
                        "type": "string",
                        "description": (
                            "Value for DOCX template placeholder 'arende.plats'."
                        ),
                    },
                },
                "required": ["diarienummer", "plats"],
                "additionalProperties": False,
            },
        },
        "required": ["customer", "arende"],
        "additionalProperties": False,
    }
    assert preparation.assistant_spec is not None
    assert "arende.diarienummer" in preparation.assistant_spec.instructions
    assert "arende.plats" in preparation.assistant_spec.instructions
    assert contracted.steps[-1].output_config == {
        "bindings": {
            "customer.name": "{{ step_b.output.structured.customer.name }}",
            "arende.diarienummer": (
                "{{ step_b.output.structured.arende.diarienummer }}"
            ),
            "arende.plats": "{{ step_b.output.structured.arende.plats }}",
        }
    }


@pytest.mark.parametrize(
    ("placeholder", "failure_code"),
    [
        ("section. value", "template_placeholder_path_invalid"),
        (
            "one.two.three.four.five.six",
            "template_placeholder_depth_exceeded",
        ),
        ("section." + "v" * 240, "template_placeholder_path_too_long"),
    ],
)
def test_contract_rejects_unresolvable_or_too_deep_materialized_path(
    placeholder: str,
    failure_code: str,
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(),
            selected_template_count=1,
            placeholders=(placeholder,),
        )

    assert exc_info.value.log_context["failure_code"] == failure_code


def test_contract_bounds_server_materialized_template_paths() -> None:
    placeholders = tuple(f"section.value_{index}" for index in range(101))

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(),
            selected_template_count=1,
            placeholders=placeholders,
        )

    assert exc_info.value.log_context["failure_code"] == (
        "template_placeholder_count_exceeded"
    )


@pytest.mark.parametrize(
    ("placeholders", "swedish"),
    [
        (("one.two.three.four.five.six",), "Fältet `one.two.three.four.five.six`"),
        (("section." + "v" * 240,), "Fältnamnet `section.vvv"),
        (
            tuple(f"section.value_{index}" for index in range(101)),
            "än som kan läggas till automatiskt i ett förberedande steg "
            f"(högst {MAX_TEMPLATE_MATERIALIZED_PATHS})",
        ),
    ],
)
def test_a_template_limit_answer_is_built_from_what_the_raise_site_reports(
    placeholders: tuple[str, ...], swedish: str
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _template_spec(), selected_template_count=1, placeholders=placeholders
        )

    answer = user_action_answer(exc_info.value, ui_language="sv")

    assert answer is not None
    assert swedish in answer.answer
    assert "None" not in answer.answer


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


def test_contract_drops_unused_json_step_before_template_fill() -> None:
    spec = _template_spec()
    unused_json_step = StepSpec(
        plan_step_ref="step_date",
        name="Prepare date",
        assistant_spec=AssistantSpec(instructions="Prepare the runtime date."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        output_contract={
            "type": "object",
            "properties": {"datum": {"type": "string"}},
            "required": ["datum"],
            "additionalProperties": False,
        },
    )
    spec = spec.model_copy(
        update={
            "steps": [
                spec.steps[0],
                spec.steps[1],
                unused_json_step,
                spec.steps[2],
            ]
        }
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("customer.name", "datum"),
    )

    assert [step.plan_step_ref for step in contracted.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert contracted.steps[-1].output_config == {
        "bindings": {
            "customer.name": "{{ step_b.output.structured.customer.name }}",
            "datum": "{{ datum }}",
        }
    }


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


def test_contract_keeps_a_retained_mapping_to_the_step_at_position_27() -> None:
    # The plan ref of position 27 was spelled "step_27", which the contract
    # read as a removed producer's runtime alias and reported as broken.
    steps = [
        StepSpec(
            plan_step_ref=make_plan_step_ref(index),
            name=f"Step {index + 1}",
            assistant_spec=AssistantSpec(instructions="Write."),
            input_source=(
                InputSource.FLOW_INPUT if index == 0 else InputSource.PREVIOUS_STEP
            ),
            input_type=InputType.TEXT,
            output_type=OutputType.TEXT,
        )
        for index in range(27)
    ]
    fill = StepSpec(
        plan_step_ref=make_plan_step_ref(27),
        name="Fill",
        assistant_spec=AssistantSpec(instructions="Fill the template."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_mode=OutputMode.TEMPLATE_FILL,
        output_type=OutputType.DOCX,
    )
    binding = "{{ " + make_plan_step_ref(26) + ".output.text }}"

    contracted = apply_template_attachment_contract(
        FlowDraftSpecCore(flow_name="Long template flow", steps=[*steps, fill]),
        selected_template_count=1,
        placeholders=("underlag",),
        existing_bindings={"underlag": binding},
    )

    assert len(contracted.steps) == 28
    assert contracted.steps[-1].output_config == {"bindings": {"underlag": binding}}


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
    # The object-typed prepared field is not bindable content, and nothing
    # says the placeholder may stay empty: the plan must produce it.
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _prepared_fields_spec(),
            selected_template_count=1,
            placeholders=("metadata",),
        )

    assert exc_info.value.repair_disposition == "model_correctable"
    assert exc_info.value.failure_code == "template_placeholder_unproduced"


def test_contract_repair_names_placeholders_escaped_and_bounded() -> None:
    placeholders = ("rad\u2028två", *(f"falt_{index}" for index in range(10)))

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            _prepared_fields_spec(),
            selected_template_count=1,
            placeholders=placeholders,
        )

    error = exc_info.value
    assert error.affected == ("rad\\u2028två", *placeholders[1:MAX_DIAGNOSTIC_NAMES])
    assert "\n- rad\\u2028två\n- falt_0\n" in error.detail
    assert "\u2028" not in error.detail
    assert error.detail.endswith(
        f"\n... and {len(placeholders) - MAX_DIAGNOSTIC_NAMES} more."
    )


def test_contract_placeholder_a_step_leaves_optional_asks_for_a_producer() -> None:
    spec = _prepared_fields_spec()
    extract = spec.steps[1]
    assert extract.output_contract is not None
    contract = deepcopy(extract.output_contract)
    contract["properties"]["handlaggare"] = {"type": ["string", "null"]}
    spec = spec.model_copy(
        update={
            "steps": [
                spec.steps[0],
                extract.model_copy(update={"output_contract": contract}),
                spec.steps[2],
            ]
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            spec, selected_template_count=1, placeholders=("handlaggare",)
        )

    assert exc_info.value.failure_code == "template_placeholder_unproduced"


def _extract_contract(
    spec: FlowDraftSpecCore,
    properties: dict[str, object],
    *,
    required: list[str] | None = None,
) -> FlowDraftSpecCore:
    """Replace the second step's contract; every property is required by default."""

    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": properties,
                "required": list(properties) if required is None else required,
                "additionalProperties": False,
            }
        }
    )
    return spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})


def test_contract_reads_a_bound_nullable_field_as_text_that_may_be_empty() -> None:
    # The fill step accepts "" as an omission and refuses null, so the field a
    # placeholder reads may not declare null. Only bound fields change.
    spec = _extract_contract(
        _template_spec(),
        {
            "arendet": {"type": ["string", "null"]},
            "diarienummer": {
                "type": ["string", "null"],
                "description": "Ärendets diarienummer.",
            },
            "handlaggare": {"type": ["string", "null"]},
            "antal": {"type": ["integer", "null"]},
            "case_id": {"type": "string"},
        },
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("Ärendet", "diarienummer"),
    )

    assert contracted.steps[-1].output_config == {
        "bindings": {
            "Ärendet": "{{ step_b.output.structured.arendet }}",
            "diarienummer": "{{ step_b.output.structured.diarienummer }}",
        }
    }
    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"] == {
        "arendet": {"type": "string"},
        "diarienummer": {
            "type": "string",
            "description": "Ärendets diarienummer.",
        },
        "handlaggare": {"type": ["string", "null"]},
        "antal": {"type": ["integer", "null"]},
        "case_id": {"type": "string"},
    }
    assert contract["required"] == [
        "arendet",
        "diarienummer",
        "handlaggare",
        "antal",
        "case_id",
    ]
    assert contracted.steps[1].assistant_spec == spec.steps[1].assistant_spec
    assert contracted.steps[0] == spec.steps[0]


def test_contract_reads_nullable_ancestors_of_a_bound_leaf_as_present() -> None:
    spec = _extract_contract(
        _template_spec(),
        {
            "sections": {
                "type": ["object", "null"],
                "properties": {"note": {"type": ["string", "null"]}},
                "required": ["note"],
                "additionalProperties": False,
            }
        },
    )

    contracted = apply_template_attachment_contract(
        spec, selected_template_count=1, placeholders=("sections.note",)
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"]["sections"] == {
        "type": "object",
        "properties": {"note": {"type": "string"}},
        "required": ["note"],
        "additionalProperties": False,
    }


def test_contract_reads_an_explicitly_named_nullable_field_as_non_null() -> None:
    spec = _extract_contract(
        _template_spec(),
        {"pris": {"type": ["number", "null"]}, "namn": {"type": ["string", "null"]}},
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("step_b.output.structured.namn", "step_b.output.structured.pris"),
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"] == {
        "pris": {"type": "number"},
        "namn": {"type": "string"},
    }


def test_contract_reads_only_the_step_a_placeholder_binds_as_non_null() -> None:
    # The latest declarer of a field is the one the placeholder reads; an
    # earlier step's same-named field is not the fill step's input.
    spec = _extract_contract(
        _template_spec(), {"arendet": {"type": ["string", "null"]}}
    )
    refine = spec.steps[1].model_copy(update={"plan_step_ref": "step_refine"})
    spec = spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], refine, spec.steps[2]]}
    )

    contracted = apply_template_attachment_contract(
        spec, selected_template_count=1, placeholders=("arendet",)
    )

    assert contracted.steps[1].output_contract == spec.steps[1].output_contract
    refined = contracted.steps[2].output_contract
    assert refined is not None
    assert refined["properties"]["arendet"] == {"type": "string"}


def test_contract_keeps_a_retained_mapping_to_a_nullable_field_and_reads_it_as_text() -> (
    None
):
    # A flow saved before the rule maps a placeholder to a nullable field. The
    # edit keeps the mapping, and the field it reads stops admitting null.
    spec = _extract_contract(
        _template_spec(), {"handlaggare": {"type": ["string", "null"]}}
    )
    binding = "{{ step_b.output.structured.handlaggare }}"

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("handlaggare",),
        existing_bindings={"handlaggare": binding},
    )

    assert contracted.steps[-1].output_config == {"bindings": {"handlaggare": binding}}
    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"]["handlaggare"] == {"type": "string"}


def test_contract_requires_the_optional_field_a_mapping_reads() -> None:
    # A key the step may leave out fails the fill step with a missing key, so
    # the field a placeholder reads is required, whether the mapping is derived
    # from the template, named in it or kept from the saved flow.
    spec = _extract_contract(
        _template_spec(),
        {
            "namn": {"type": ["string", "null"]},
            "adress": {"type": "string"},
            "kommentar": {"type": "string"},
        },
        required=[],
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("step_b.output.structured.namn", "adress"),
        existing_bindings={"adress": "{{ step_b.output.structured.adress }}"},
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["required"] == ["namn", "adress"]
    assert contract["properties"] == {
        "namn": {"type": "string"},
        "adress": {"type": "string"},
        "kommentar": {"type": "string"},
    }


def test_contract_requires_every_optional_object_above_a_mapped_field() -> None:
    spec = _extract_contract(
        _template_spec(),
        {
            "sections": {
                "type": "object",
                "properties": {"note": {"type": "string"}, "other": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            }
        },
        required=[],
    )
    binding = "{{ step_b.output.structured.sections.note }}"

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("avsnitt",),
        existing_bindings={"avsnitt": binding},
    )

    assert contracted.steps[-1].output_config == {"bindings": {"avsnitt": binding}}
    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["required"] == ["sections"]
    assert contract["properties"]["sections"]["required"] == ["note"]


def _projecting_consumer(
    contract: dict[str, object],
    *fields: str,
    plan_step_ref: str = "step_next",
    name: str = "Refine",
) -> StepSpec:
    """A JSON step whose input is a structured projection of `step_b` fields."""

    bindings = {
        "source_refs": [
            {"step_ref": "step_b", "output": "structured", "field_path": field}
            for field in fields
        ]
    }
    return StepSpec(
        plan_step_ref=plan_step_ref,
        name=name,
        assistant_spec=AssistantSpec(instructions="Refine."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        input_bindings=bindings,
        input_contract=derive_structured_projection_contract(
            input_bindings=bindings, source_contracts_by_step_ref={"step_b": contract}
        ),
        output_type=OutputType.JSON,
        output_contract={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    )


def _spec_with_projecting_consumers() -> FlowDraftSpecCore:
    spec = _extract_contract(
        _template_spec(),
        {
            "arendet": {"type": ["string", "null"]},
            "kommentar": {"type": ["string", "null"]},
        },
    )
    contract = spec.steps[1].output_contract
    assert contract is not None
    consumers = [
        _projecting_consumer(contract, "arendet"),
        _projecting_consumer(
            contract, "kommentar", plan_step_ref="step_other", name="Refine more"
        ),
    ]
    return spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], *consumers, spec.steps[2]]}
    )


def test_contract_derives_a_structured_projection_again_from_the_narrowed_field() -> (
    None
):
    # A projection copies the field it selects and the graph requires the copy
    # to match exactly, so narrowing the producer moves its copies with it.
    spec = _spec_with_projecting_consumers()

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("arendet", "summary"),
        inherited_template_asset_id=uuid4(),
    )

    projecting, untouched = contracted.steps[2], contracted.steps[3]
    assert projecting.input_contract == {
        "type": "object",
        "properties": {"arendet": {"type": "string"}},
        "required": ["arendet"],
        "additionalProperties": False,
    }
    assert untouched == spec.steps[3]
    assert not collect_step_graph_issues(
        flow_step_validation_views_from_draft_spec(contracted.steps),
        metadata_json=metadata_json_from_authoring_form_fields(contracted.form_fields),
        require_complete_template_fill_config=True,
    )


def test_a_step_scoped_edit_never_rewrites_a_saved_step_and_checks_the_selected_one() -> (
    None
):
    # A step-scoped edit rewrites nothing for the template: the selected step's
    # fields are checked, and a field that is not plain is refused with the
    # whole-flow edit as the remedy.
    spec = _spec_with_projecting_consumers()

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            spec,
            selected_template_count=1,
            placeholders=("arendet", "summary"),
            is_frozen=lambda step: step.plan_step_ref != "step_b",
        )

    error = exc_info.value
    assert error.failure_code == "template_bound_field_not_plain"
    assert error.repair_disposition == "model_correctable"
    assert "'arendet'" in error.detail
    assert "'Extract'" in error.detail
    assert "whole flow" in error.detail
    assert "one type" in error.detail


def test_a_step_scoped_edit_accepts_a_selected_step_whose_fields_are_plain() -> None:
    spec = _extract_contract(
        _template_spec(),
        {"arendet": {"type": "string"}, "kommentar": {"type": ["string", "null"]}},
    )
    contract = spec.steps[1].output_contract
    assert contract is not None
    consumer = _projecting_consumer(contract, "arendet")
    spec = spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], consumer, spec.steps[2]]}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("arendet",),
        drop_unused_predecessor=False,
        is_frozen=lambda step: step.plan_step_ref != "step_b",
    )

    assert contracted.steps[1:3] == spec.steps[1:3]


def test_a_step_scoped_edit_refuses_an_unrelated_field_that_is_not_plain() -> None:
    # `kommentar` is not what the frozen consumer projects, and the selected
    # step still declares it nullable: the template cannot rely on it.
    spec = _extract_contract(
        _template_spec(),
        {"arendet": {"type": "string"}, "kommentar": {"type": ["string", "null"]}},
    )
    contract = spec.steps[1].output_contract
    assert contract is not None
    consumer = _projecting_consumer(contract, "arendet")
    spec = spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], consumer, spec.steps[2]]}
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            spec,
            selected_template_count=1,
            placeholders=("arendet", "kommentar"),
            is_frozen=lambda step: step.plan_step_ref != "step_b",
        )

    assert "'kommentar'" in exc_info.value.detail


def test_contract_leaves_a_frozen_step_as_it_was_saved() -> None:
    spec = _spec_with_projecting_consumers()

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("arendet", "summary"),
        is_frozen=lambda step: step.plan_step_ref == "step_b",
    )

    assert contracted.steps[1] == spec.steps[1]
    assert contracted.steps[2] == spec.steps[2]


@pytest.mark.parametrize(
    ("declared", "narrowed"),
    [
        ({"type": ["string", "null"]}, "string"),
        ({"type": ["null", "string"]}, "string"),
        ({"type": ["string"]}, "string"),
        ({"type": ["integer", "null"]}, "integer"),
        ({"type": ["number", "null"]}, "number"),
        ({"type": ["boolean", "null"]}, "boolean"),
    ],
)
def test_contract_narrows_a_type_list_of_one_type_and_touches_nothing_else(
    declared: dict[str, object], narrowed: str
) -> None:
    # A node that only declares a type and annotations can be edited: nothing
    # on it asserts anything that the edit could turn unsatisfiable.
    extras = {
        "title": "T",
        "description": "D",
        "examples": ["a"],
        "default": "a",
        "$comment": "c",
    }
    spec = _extract_contract(_template_spec(), {"handlaggare": {**declared, **extras}})
    binding = "{{ step_b.output.structured.handlaggare }}"

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("handlaggare",),
        existing_bindings={"handlaggare": binding},
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"]["handlaggare"] == {"type": narrowed, **extras}
    assert template_bound_path_ok(contract, ("handlaggare",))


@pytest.mark.parametrize(
    "declared",
    [
        {"type": "string", "minLength": 1},
        {"type": "integer", "minimum": 0, "title": "Antal"},
        {"type": "string", "enum": ["a", "b"], "description": "D"},
        {"type": "boolean"},
    ],
)
def test_contract_leaves_a_required_field_of_one_type_exactly_as_declared(
    declared: dict[str, object],
) -> None:
    spec = _extract_contract(_template_spec(), {"handlaggare": declared})

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("handlaggare",),
        existing_bindings={"handlaggare": "{{ step_b.output.structured.handlaggare }}"},
    )

    assert contracted.steps[1] == spec.steps[1]


_GUARD = {"allOf": [{"not": {"required": ["secret"]}}]}


def _guarded_contract(leaf: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        **_GUARD,
        "properties": {
            "sections": {
                "type": "object",
                **_GUARD,
                "properties": {"note": leaf},
                "required": ["note"],
                "additionalProperties": False,
            }
        },
        "required": ["sections"],
        "additionalProperties": False,
    }


def _apply_to(contract: dict[str, object]) -> FlowDraftSpecCore:
    spec = _template_spec()
    extract = spec.steps[1].model_copy(update={"output_contract": contract})
    spec = spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})
    return apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("avsnitt",),
        existing_bindings={"avsnitt": "{{ step_b.output.structured.sections.note }}"},
    )


def test_contract_keeps_an_ancestor_constraint_that_forbids_a_key_byte_for_byte() -> (
    None
):
    # The path is already ok: nothing on the schema is touched, guards included.
    contract = _guarded_contract({"type": "string"})

    contracted = _apply_to(contract)

    assert contracted.steps[1].output_contract == contract
    assert json.dumps(contracted.steps[1].output_contract, sort_keys=True) == (
        json.dumps(contract, sort_keys=True)
    )


def test_contract_edits_nothing_and_refuses_when_a_guard_sits_beside_a_needed_edit() -> (
    None
):
    # The field needs narrowing and an ancestor carries a constraint: an edit
    # could interact with it, so nothing is edited and the plan is sent back.
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _apply_to(_guarded_contract({"type": ["string", "null"]}))

    assert exc_info.value.failure_code == "template_bound_field_not_plain"
    assert "'sections.note'" in exc_info.value.detail
    assert "without other constraints" in exc_info.value.detail


@pytest.mark.parametrize(
    "contract",
    [
        pytest.param(
            {
                "type": "object",
                "allOf": [{"properties": {"sections": {"const": None}}}],
                "properties": {
                    "sections": {
                        "type": ["object", "null"],
                        "properties": {"note": {"type": "string"}},
                        "required": [],
                    }
                },
                "required": [],
            },
            id="ancestor-allof-const-null",
        ),
        pytest.param(
            {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {"note": {"type": "string", "enum": [None]}},
                        "required": [],
                    }
                },
                "required": ["sections"],
            },
            id="optional-child-enum-null-newly-required",
        ),
        pytest.param(
            {
                "type": "object",
                "$defs": {"alias": {"$ref": "#/properties/sections/properties/note"}},
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {"note": {"type": ["string", "null"]}},
                        "required": ["note"],
                    },
                    "alias": {"$ref": "#/$defs/alias", "const": None},
                },
                "required": ["sections"],
            },
            id="sibling-ref-const-null",
        ),
        pytest.param(
            {
                "type": ["object", "null"],
                "properties": {
                    "sections": {
                        "type": "object",
                        "properties": {"note": {"type": "string"}},
                        "required": ["note"],
                    }
                },
                "required": ["sections", "phantom"],
                "additionalProperties": False,
            },
            id="closed-object-requires-an-undeclared-key",
        ),
    ],
)
def test_contract_refuses_the_inputs_an_interacting_assertion_would_break(
    contract: dict[str, object],
) -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _apply_to(contract)

    assert exc_info.value.failure_code == "template_bound_field_not_plain"
    assert exc_info.value.repair_disposition == "model_correctable"
    assert "'sections.note'" in exc_info.value.detail
    assert "'Extract'" in exc_info.value.detail


def test_a_compile_over_a_remote_ref_refuses_and_makes_no_request() -> None:
    with local_listener() as (base, requested):
        contract = {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "object",
                    "properties": {"note": {"type": "string", "$ref": f"{base}/x"}},
                    "required": [],
                }
            },
            "required": ["sections"],
        }
        with pytest.raises(AIBuilderArchitectureError) as exc_info:
            _apply_to(contract)

    assert exc_info.value.failure_code == "template_bound_field_not_plain"
    assert "'sections.note'" in exc_info.value.detail
    assert requested == []


def test_a_contract_the_builder_generates_is_plain_and_repaired_as_a_whole() -> None:
    # Every keyword the Builder writes into a contract is structural or an
    # annotation, so the common case is always repaired, nested groups, arrays
    # of objects and open groups included.
    fields = [
        StructuredFieldDraft(
            name="arende",
            field_type="object",
            description="Ärendet",
            fields=[
                StructuredFieldDraft(
                    name="note", field_type="string", description="N", nullable=True
                ),
                StructuredFieldDraft(
                    name="antal",
                    field_type="number",
                    description="A",
                    required=False,
                    nullable=True,
                ),
            ],
        ),
        StructuredFieldDraft(
            name="rader",
            field_type="array",
            description="R",
            item_fields=[
                StructuredFieldDraft(name="text", field_type="string", description="T")
            ],
        ),
        StructuredFieldDraft(
            name="oppen",
            field_type="object",
            description="O",
            allow_additional_properties=True,
        ),
    ]
    contract = compile_output_contract(fields)
    assert contract is not None
    assert all_plain(contract)

    spec = _template_spec()
    extract = spec.steps[1].model_copy(update={"output_contract": contract})
    spec = spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})
    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=(
            "step_b.output.structured.arende.note",
            "step_b.output.structured.arende.antal",
        ),
    )

    repaired = contracted.steps[1].output_contract
    assert repaired is not None
    assert template_bound_path_ok(repaired, ("arende", "note"))
    assert template_bound_path_ok(repaired, ("arende", "antal"))
    assert repaired["properties"]["arende"]["properties"]["antal"]["type"] == "number"
    assert repaired["properties"]["rader"] == contract["properties"]["rader"]
    assert jsonschema.Draft202012Validator(repaired).is_valid(witness(repaired))


def test_contract_keeps_a_bound_integer_an_integer_for_the_steps_that_read_it() -> None:
    spec = _extract_contract(
        _template_spec(), {"antal": {"type": ["integer", "null"], "title": "Antal"}}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("step_b.output.structured.antal",),
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"]["antal"] == {"type": "integer", "title": "Antal"}


@pytest.mark.parametrize(
    "declared",
    [
        {"type": "null"},
        {"type": ["null"]},
        {"type": ["string", "integer"]},
        {"type": ["string", "integer", "null"]},
        {"enum": ["a", None]},
        {"enum": ["a", "b"]},
        {"const": "final"},
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {"oneOf": [{"type": "string"}, {"type": "number"}]},
        {"type": "string", "$ref": "#/$defs/title"},
        # Narrowing these would make a contract no value satisfies.
        {"type": ["string", "null"], "enum": [None]},
        {"type": ["string", "null"], "enum": ["a", None]},
        {"type": ["integer", "null"], "minimum": 0},
        {"type": ["string", "null"], "not": {"minLength": 1}},
    ],
)
def test_contract_refuses_a_field_without_one_type_and_names_the_remedy(
    declared: dict[str, object],
) -> None:
    spec = _extract_contract(_template_spec(), {"handlaggare": declared})

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            spec,
            selected_template_count=1,
            placeholders=("handlaggare",),
            existing_bindings={
                "handlaggare": "{{ step_b.output.structured.handlaggare }}"
            },
        )

    error = exc_info.value
    assert error.failure_code == "template_bound_field_not_plain"
    assert error.repair_disposition == "model_correctable"
    assert "'handlaggare'" in error.detail
    assert "'Extract'" in error.detail
    assert "one type" in error.detail
    assert "output_fields" in error.detail


@pytest.mark.parametrize(
    "above",
    [
        {},
        {"type": ["object", "string"]},
        {"$ref": "#/$defs/sections"},
        # Adding the key to `required` would make every output invalid.
        {"type": "object", "required": [], "not": {"required": ["note"]}},
        {"type": ["object", "null"], "required": ["note"], "allOf": [{}]},
        {"type": "object", "required": [], "maxProperties": 0},
    ],
)
def test_contract_refuses_an_object_it_cannot_make_one_type(
    above: dict[str, object],
) -> None:
    # An object schema without "type" accepts anything, null included, and no
    # other keyword changes that.
    sections = {
        "properties": {"note": {"type": "string"}},
        "required": ["note"],
        **above,
    }
    spec = _extract_contract(_template_spec(), {"sections": sections})

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        apply_template_attachment_contract(
            spec,
            selected_template_count=1,
            placeholders=("avsnitt",),
            existing_bindings={
                "avsnitt": "{{ step_b.output.structured.sections.note }}"
            },
        )

    assert exc_info.value.failure_code == "template_bound_field_not_plain"
    assert "'sections.note'" in exc_info.value.detail


def test_contract_leaves_an_explicitly_named_container_for_publication_to_name() -> (
    None
):
    spec = _extract_contract(
        _template_spec(),
        {"facts": {"type": "array", "items": {"type": "string"}}},
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("step_b.output.structured.facts",),
    )

    assert contracted.steps[1] == spec.steps[1]


def test_contract_reads_a_nullable_result_object_above_the_bound_field_as_present() -> (
    None
):
    spec = _extract_contract(_template_spec(), {"arendet": {"type": "string"}})
    extract = spec.steps[1].model_copy(
        update={
            "output_contract": {
                **(spec.steps[1].output_contract or {}),
                "type": ["object", "null"],
            }
        }
    )
    spec = spec.model_copy(update={"steps": [spec.steps[0], extract, spec.steps[2]]})

    contracted = apply_template_attachment_contract(
        spec, selected_template_count=1, placeholders=("arendet",)
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["type"] == "object"


def test_contract_leaves_a_mapping_the_new_template_no_longer_reads_untouched() -> None:
    spec = _extract_contract(
        _template_spec(),
        {"handlaggare": {"type": ["string", "null"]}, "arendet": {"type": "string"}},
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("arendet",),
        existing_bindings={"handlaggare": "{{ step_b.output.structured.handlaggare }}"},
    )

    contract = contracted.steps[1].output_contract
    assert contract is not None
    assert contract["properties"]["handlaggare"] == {"type": ["string", "null"]}


def test_a_compiled_nullable_bound_field_is_publishable_and_feeds_its_consumer() -> (
    None
):
    # The next step keeps reading the field as it always did (string or null);
    # a producer that is only text still satisfies that input contract.
    fields = {"arendet": {"type": ["string", "null"]}}
    spec = _extract_contract(_template_spec(), fields)
    consumer = StepSpec(
        plan_step_ref="step_next",
        name="Refine",
        assistant_spec=AssistantSpec(instructions="Refine."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        input_contract={
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        },
        output_type=OutputType.JSON,
        output_contract={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    )
    spec = spec.model_copy(
        update={"steps": [spec.steps[0], spec.steps[1], consumer, spec.steps[2]]}
    )

    contracted = apply_template_attachment_contract(
        spec,
        selected_template_count=1,
        placeholders=("arendet", "summary"),
        inherited_template_asset_id=uuid4(),
    )

    assert not collect_step_graph_issues(
        flow_step_validation_views_from_draft_spec(contracted.steps),
        metadata_json=metadata_json_from_authoring_form_fields(contracted.form_fields),
        require_complete_template_fill_config=True,
    )


def test_contract_requires_a_declared_field_that_renders_nothing_when_empty() -> None:
    # An omitted optional date reads as null, and a placeholder bound to null
    # fails the render, so the template makes that field required.
    spec = _template_spec().model_copy(
        update={
            "form_fields": [
                FormFieldSpec(
                    name="beslutsdatum", type="date", label="Datum", required=False
                )
            ]
        }
    )

    contracted = apply_template_attachment_contract(
        spec, selected_template_count=1, placeholders=("beslutsdatum",)
    )

    assert [(field.name, field.required) for field in contracted.form_fields or ()] == [
        ("beslutsdatum", True)
    ]


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
