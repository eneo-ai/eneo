from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.step_lineage import build_step_ref_mapping
from eneo.flows.variable_resolver import (
    FlowVariableResolver,
    iter_template_expressions,
)
from eneo.main.exceptions import BadRequestException, TypedIOValidationException


def _result(step_order: int, output_payload: dict) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={"question": "Who is responsible?"},
        effective_prompt="Summarize input.",
        output_payload_json=output_payload,
        model_parameters_json={"temperature": 0.2},
        num_tokens_input=10,
        num_tokens_output=12,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def test_build_context_exposes_flow_input_and_step_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"citizen_name": "Anna"},
        prior_results=[
            _result(step_order=1, output_payload={"summary": "Case summary"}),
            _result(step_order=2, output_payload={"classification": {"code": "open"}}),
        ],
    )

    assert context["flow"]["input"]["citizen_name"] == "Anna"
    assert context["flow_input"]["citizen_name"] == "Anna"
    assert context["step_1"]["output"]["summary"] == "Case summary"
    assert context["step_2"]["output"]["classification"]["code"] == "open"


def test_interpolate_resolves_nested_values():
    resolver = FlowVariableResolver()
    template = (
        "Citizen: {{ flow.input.citizen_name }} | "
        "Summary: {{step_1.output.summary}} | "
        "Status: {{ step_2.output.classification.code }}"
    )
    context = resolver.build_context(
        flow_input={"citizen_name": "Anna"},
        prior_results=[
            _result(step_order=1, output_payload={"summary": "Case summary"}),
            _result(step_order=2, output_payload={"classification": {"code": "open"}}),
        ],
    )

    rendered = resolver.interpolate(template=template, context=context)
    assert rendered == "Citizen: Anna | Summary: Case summary | Status: open"


def test_interpolate_supports_flow_input_alias():
    resolver = FlowVariableResolver()
    template = "Citizen: {{flow_input.citizen_name}}"
    context = resolver.build_context(
        flow_input={"citizen_name": "Anna"},
        prior_results=[],
    )

    rendered = resolver.interpolate(template=template, context=context)
    assert rendered == "Citizen: Anna"


def test_interpolate_raises_on_missing_reference():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"citizen_name": "Anna"},
        prior_results=[
            _result(step_order=1, output_payload={"summary": "Case summary"})
        ],
    )

    with pytest.raises(BadRequestException):
        resolver.interpolate(
            template="{{ step_2.output.classification.code }}",
            context=context,
        )


def test_build_context_exposes_friendly_field_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={
            "Namn på brukare": "Anna Andersson",
            "Personnummer": "19121212-1212",
        },
        prior_results=[],
    )

    assert context["Namn på brukare"] == "Anna Andersson"
    assert context["Personnummer"] == "19121212-1212"


def test_build_context_exposes_previous_step_alias_for_step_two():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[
            _result(step_order=1, output_payload={"text": "Sammanfattning steg 1"})
        ],
        current_step_order=2,
    )

    assert context["föregående_steg"] == "Sammanfattning steg 1"


def test_context_hides_file_backed_metadata_and_keeps_structured_output() -> None:
    file_id = uuid4()
    result = _result(
        step_order=1,
        output_payload={
            "text": "preview",
            "structured": {"decision": "approve"},
            "text_overflow": {
                "generated_file_ids": [str(file_id)],
                "inline_text_bytes": 7,
                "full_text_bytes": 20,
            },
        },
    )

    context = FlowVariableResolver().build_context(
        flow_input={},
        prior_results=[result],
        current_step_order=2,
        step_names_by_order={1: "Previous report"},
        step_ref_mapping={"Previous report": 1},
    )

    output = context["step_1"]["output"]
    assert set(output) == {"text", "structured"}
    assert output["text"] != "preview"
    assert "text_overflow" not in output
    assert (
        FlowVariableResolver().interpolate(
            "{{ step_1.output.structured.decision }}",
            context,
        )
        == "approve"
    )
    assert FlowVariableResolver().interpolate("{{ step_1.status }}", context)


@pytest.mark.parametrize(
    "reference",
    [
        "step_1",
        "step_1.output",
        "step_1.output.text",
        "föregående_steg",
        "Previous report",
    ],
)
def test_interpolate_rejects_each_file_backed_text_alias_with_typed_code(
    reference: str,
) -> None:
    file_id = uuid4()
    context = FlowVariableResolver().build_context(
        flow_input={},
        prior_results=[
            _result(
                step_order=1,
                output_payload={
                    "text": "preview",
                    "structured": {"decision": "approve"},
                    "text_overflow": {
                        "generated_file_ids": [str(file_id)],
                        "inline_text_bytes": 7,
                        "full_text_bytes": 20,
                    },
                },
            )
        ],
        current_step_order=2,
        step_names_by_order={1: "Previous report"},
        step_ref_mapping={"Previous report": 1},
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        FlowVariableResolver().interpolate(f"{{{{ {reference} }}}}", context)

    assert exc_info.value.code == FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value
    assert "generated output file" in str(exc_info.value)
    assert "preview" not in str(exc_info.value)
    assert str(file_id) not in str(exc_info.value)


def test_build_context_defers_malformed_text_failure_until_text_is_referenced() -> None:
    context = FlowVariableResolver().build_context(
        flow_input={},
        prior_results=[
            _result(
                step_order=1,
                output_payload={
                    "text": "preview",
                    "structured": {"decision": "approve"},
                    "text_overflow": {
                        "generated_file_ids": [],
                        "inline_text_bytes": 7,
                        "full_text_bytes": 20,
                    },
                },
            )
        ],
    )

    assert (
        FlowVariableResolver().interpolate(
            "{{ step_1.output.structured.decision }}",
            context,
        )
        == "approve"
    )
    assert "text_overflow" not in context["step_1"]["output"]
    with pytest.raises(TypedIOValidationException) as exc_info:
        FlowVariableResolver().interpolate("{{ step_1.output }}", context)

    assert exc_info.value.code == FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value
    assert "malformed persisted text" in str(exc_info.value)
    assert "preview" not in str(exc_info.value)


def test_build_context_exposes_named_step_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[
            _result(step_order=1, output_payload={"text": "Steg 1 text"}),
            _result(step_order=2, output_payload={"text": "Steg 2 text"}),
        ],
        current_step_order=3,
        step_names_by_order={
            1: "Sammanfattning av samtalet",
            2: "Identifiera behov",
        },
        step_ref_mapping={
            "Sammanfattning av samtalet": 1,
            "Identifiera behov": 2,
        },
    )

    assert context["Sammanfattning av samtalet"] == "Steg 1 text"
    assert context["Identifiera behov"] == "Steg 2 text"


@pytest.mark.parametrize("authored_ref_field", ["plan_step_ref", "existing_step_ref"])
def test_interpolate_rejects_step_label_colliding_with_other_authored_ref(
    authored_ref_field: str,
) -> None:
    colliding_label = "shared_ref"
    steps = [
        {
            "step_order": 1,
            authored_ref_field: colliding_label,
            "user_description": "Authored owner",
        },
        {
            "step_order": 2,
            "user_description": f" {colliding_label} ",
        },
    ]
    context = FlowVariableResolver().build_context(
        flow_input={},
        prior_results=[
            _result(step_order=1, output_payload={"text": "authored owner text"}),
            _result(step_order=2, output_payload={"text": "display label text"}),
        ],
        current_step_order=3,
        step_names_by_order={1: "Authored owner", 2: f" {colliding_label} "},
        step_ref_mapping=build_step_ref_mapping(steps),
    )

    with pytest.raises(BadRequestException) as exc_info:
        FlowVariableResolver().interpolate(f"{{{{ {colliding_label} }}}}", context)

    assert "authored owner text" not in str(exc_info.value)
    assert "display label text" not in str(exc_info.value)


def test_build_context_does_not_overwrite_reserved_key_with_step_label() -> None:
    context = FlowVariableResolver().build_context(
        flow_input={},
        prior_results=[_result(step_order=1, output_payload={"text": "step text"})],
        current_step_order=2,
        step_names_by_order={1: "datum"},
        step_ref_mapping={"datum": 1},
    )

    assert context["datum"] != "step text"


def test_build_context_exposes_context_aware_system_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={
            "transkribering": "Detta är en transkribering.",
            "text": "Direkt text in",
            "json": {"key": "value"},
        },
        prior_results=[],
    )

    assert context["transkribering"] == "Detta är en transkribering."
    assert context["indata_text"] == "Direkt text in"
    assert context["indata_json"] == {"key": "value"}
    assert context["datum"].count("-") == 2


def test_build_context_does_not_overwrite_reserved_keys_from_friendly_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={
            "flow_input": "should_not_override",
            "flow": "should_not_override",
            "step_1": "should_not_override",
            "indata_json": "should_not_override",
            "Namn på brukare": "Anna",
        },
        prior_results=[],
    )

    assert isinstance(context["flow_input"], dict)
    assert isinstance(context["flow"], dict)
    assert "step_1" not in context
    assert context["Namn på brukare"] == "Anna"


def test_namespaced_flow_input_reads_reserved_user_field_without_overwriting_system_alias():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"datum": "2026-05-06", "flow_input": "user supplied value"},
        prior_results=[],
    )

    assert context["flow_input"]["datum"] == "2026-05-06"
    assert (
        resolver.interpolate(template="{{ flow_input.datum }}", context=context)
        == "2026-05-06"
    )
    assert (
        resolver.interpolate(template="{{ flow_input.flow_input }}", context=context)
        == "user supplied value"
    )
    assert resolver.interpolate(template="{{ datum }}", context=context) != "2026-05-06"


def test_iter_template_expressions_extracts_all_expressions():
    expressions = iter_template_expressions(
        "Hej {{ flow_input.name }} och {{step_1.output.summary}} med {{ custom.value }}"
    )

    assert expressions == ["flow_input.name", "step_1.output.summary", "custom.value"]


def test_interpolate_tolerates_whitespace_around_path_separators():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"citizen_name": "Anna"},
        prior_results=[],
    )

    rendered = resolver.interpolate(
        template="Citizen: {{ flow_input . citizen_name }}",
        context=context,
    )

    assert rendered == "Citizen: Anna"


def test_interpolate_serializes_non_ascii_json_values_without_ascii_escaping():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"structured": {"namn": "Åke", "stad": "Örebro"}},
        prior_results=[],
    )

    rendered = resolver.interpolate(
        template="Payload: {{ indata_json }}",
        context=context,
    )

    assert rendered == "Payload: namn: Åke\nstad: Örebro"


def test_interpolate_renders_short_step_input_file_id_lists_as_comma_separated_values():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[],
        current_step_input={"file_ids": ["miljo", "buller", "trafik"]},
    )

    rendered = resolver.interpolate(
        template="Tags: {{ step_input.file_ids }}",
        context=context,
    )

    assert rendered == "Tags: miljo, buller, trafik"


def test_interpolate_error_includes_available_keys_for_small_dicts():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"namn": "Anna", "roll": "Handläggare"},
        prior_results=[],
    )

    with pytest.raises(BadRequestException, match="Available keys: namn, roll"):
        resolver.interpolate(
            template="{{ flow_input.person }}",
            context=context,
        )


def test_interpolate_raises_for_non_numeric_list_index():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[],
        current_step_input={"file_ids": ["f1", "f2"]},
    )

    with pytest.raises(BadRequestException, match="Expected numeric index"):
        resolver.interpolate(
            template="{{ step_input.file_ids.first }}",
            context=context,
        )


def test_resolve_path_returns_list_when_path_ends_on_list_value():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[
            _result(
                step_order=1,
                output_payload={
                    "structured": {
                        "risker": [
                            {"rubrik": "Budgetrisk"},
                            {"rubrik": "Tidplansrisk"},
                        ]
                    }
                },
            )
        ],
    )

    assert resolver.resolve_path(
        context,
        "step_1.output.structured.risker",
    ) == [{"rubrik": "Budgetrisk"}, {"rubrik": "Tidplansrisk"}]


def test_resolve_path_requires_numeric_index_to_read_list_item_field():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[
            _result(
                step_order=1,
                output_payload={
                    "structured": {
                        "risker": [
                            {"rubrik": "Budgetrisk"},
                        ]
                    }
                },
            )
        ],
    )

    with pytest.raises(BadRequestException, match="Expected numeric index"):
        resolver.resolve_path(context, "step_1.output.structured.risker.rubrik")

    assert (
        resolver.resolve_path(context, "step_1.output.structured.risker.0.rubrik")
        == "Budgetrisk"
    )


def test_interpolate_raises_for_list_index_out_of_range():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[],
        current_step_input={"file_ids": ["f1"]},
    )

    with pytest.raises(BadRequestException, match="out of range"):
        resolver.interpolate(
            template="{{ step_input.file_ids.3 }}",
            context=context,
        )


def test_build_context_skips_friendly_alias_with_dot_notation():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"person.namn": "Should be skipped", "Namn": "Anna"},
        prior_results=[],
    )

    assert "person.namn" not in context
    assert context["Namn"] == "Anna"
