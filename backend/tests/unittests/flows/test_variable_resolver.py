from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.variable_resolver import FlowVariableResolver
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
