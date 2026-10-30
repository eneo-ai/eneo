"""A tool argument is a fixed value or one whole reference, never composed text."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.tool_input import (
    BoundArgument,
    ToolInputConfig,
)
from eneo.flows.flow_run_provenance import FlowResolvedInputStepResultSource
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.json_types import JsonValue

_IDS = {"mcp_server_id": str(uuid4()), "tool_id": str(uuid4())}


def _config(arguments: dict[str, JsonValue]) -> ToolInputConfig:
    return ToolInputConfig.model_validate({**_IDS, "arguments": arguments})


def test_bound_arguments_are_the_whole_references_and_nothing_else() -> None:
    # Kills the mutants that read a fixed value as a binding (its braces-free
    # text would be looked up as a path) or miss a bound one (lineage and the
    # run form would not know the step reads it).
    config = _config(
        {
            "view": "v_daily_features",
            "limit": 10,
            "flags": ["a", "b"],
            "days": "  {{ step_1.output.structured.days }} ",
            "from": "{{flow_input.from_date}}",
        }
    )

    assert config.bound_arguments() == (
        BoundArgument(
            name="days",
            template="  {{ step_1.output.structured.days }} ",
            expression="step_1.output.structured.days",
        ),
        BoundArgument(
            name="from",
            template="{{flow_input.from_date}}",
            expression="flow_input.from_date",
        ),
    )
    assert config.reference_sites() == [
        (("tool", "arguments", "days"), "  {{ step_1.output.structured.days }} "),
        (("tool", "arguments", "from"), "{{flow_input.from_date}}"),
    ]


def test_a_reference_is_read_with_its_type_and_leaves_an_evidence_edge() -> None:
    # Kills the mutant that renders the referenced value as prompt text (a
    # list of days would reach the tool as one string) and the one that reads
    # it without the evidence edge every other read of a step result leaves.
    days = ["2026-01-03", "2026-01-09"]
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    step_id = uuid4()
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=step_id,
        step_order=1,
        status=FlowStepResultStatus.COMPLETED,
        current_attempt_no=1,
        output_payload_json={"structured": {"days": days}, "text": "{}"},
        created_at=now,
        updated_at=now,
    )
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence({}, [result], current_step_order=2)

    value, edge = resolver.resolve_reference_with_evidence(
        "step_1.output.structured.days", context, binding_ref="tool.arguments.days"
    )

    assert value == days
    assert edge.binding_ref == "tool.arguments.days:step_1.output.structured.days"
    assert isinstance(edge.source, FlowResolvedInputStepResultSource)
    assert edge.source.source_step_id == step_id
