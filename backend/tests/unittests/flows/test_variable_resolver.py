from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.variable_resolver import FlowVariableResolver, iter_template_expressions
from intric.main.exceptions import BadRequestException


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
        tool_calls_metadata=None,
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
        prior_results=[_result(step_order=1, output_payload={"summary": "Case summary"})],
    )

    with pytest.raises(BadRequestException):
        resolver.interpolate(
            template="{{ step_2.output.classification.code }}",
            context=context,
        )


def test_build_context_exposes_friendly_field_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"Namn på brukare": "Anna Andersson", "Personnummer": "19121212-1212"},
        prior_results=[],
    )

    assert context["Namn på brukare"] == "Anna Andersson"
    assert context["Personnummer"] == "19121212-1212"


def test_build_context_exposes_previous_step_alias_for_step_two():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={},
        prior_results=[_result(step_order=1, output_payload={"text": "Sammanfattning steg 1"})],
        current_step_order=2,
    )

    assert context["föregående_steg"] == "Sammanfattning steg 1"


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
    )

    assert context["Sammanfattning av samtalet"] == "Steg 1 text"
    assert context["Identifiera behov"] == "Steg 2 text"


def test_build_context_exposes_context_aware_system_aliases():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={
            "transkribering": "Detta är en transkribering.",
            "text": "Direkt text in",
            "json": {"key": "value"},
            "file_ids": ["f1", "f2"],
        },
        prior_results=[],
    )

    assert context["transkribering"] == "Detta är en transkribering."
    assert context["indata_text"] == "Direkt text in"
    assert context["indata_json"] == {"key": "value"}
    assert context["indata_filer"] == ["f1", "f2"]


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

    assert rendered == 'Payload: {"namn": "Åke", "stad": "Örebro"}'


def test_interpolate_raises_for_non_numeric_list_index():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"file_ids": ["f1", "f2"]},
        prior_results=[],
    )

    with pytest.raises(BadRequestException, match="Expected numeric index"):
        resolver.interpolate(
            template="{{ indata_filer.first }}",
            context=context,
        )


def test_interpolate_raises_for_list_index_out_of_range():
    resolver = FlowVariableResolver()
    context = resolver.build_context(
        flow_input={"file_ids": ["f1"]},
        prior_results=[],
    )

    with pytest.raises(BadRequestException, match="out of range"):
        resolver.interpolate(
            template="{{ indata_filer.3 }}",
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
