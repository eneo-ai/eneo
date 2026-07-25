from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.runtime.step_input_resolution import build_resolved_input_edges


def _step(*, step_order: int, input_source: str) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


def _result(*, step_order: int, attempt_no: int | None = 1) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        status="completed",
        current_attempt_no=attempt_no,
        created_at=now,
        updated_at=now,
    )


def test_previous_step_edge_pins_the_exact_source_attempt() -> None:
    """A rerun produces a new attempt; the edge must say which one was consumed."""
    upstream = _result(step_order=1, attempt_no=3)

    edges = build_resolved_input_edges(
        step=_step(step_order=2, input_source="previous_step"),
        source_text="upstream output",
        used_question_binding=False,
        prior_results=[upstream],
        state=None,
    )

    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_kind == "previous_step"
    assert edge.source_step_id == upstream.step_id
    assert edge.source_step_order == 1
    assert edge.source_attempt_no == 3


def test_previous_step_replaced_by_flow_input_binding_yields_no_upstream_edge() -> None:
    """Configured for previous_step, but a flow-input binding supplied the value.

    No upstream value was read, so claiming an upstream edge would be a
    configuration-derived guess rather than what happened.
    """
    upstream = _result(step_order=1)

    edges = build_resolved_input_edges(
        step=_step(step_order=2, input_source="previous_step"),
        source_text="value from the flow input",
        used_question_binding=True,
        prior_results=[upstream],
        state=None,
    )

    assert len(edges) == 1
    assert edges[0].source_kind == "flow_input"
    assert edges[0].selector == "question"
    assert edges[0].source_step_id is None
    assert all(edge.source_kind != "previous_step" for edge in edges)


def test_previous_step_with_no_completed_upstream_records_no_edge() -> None:
    edges = build_resolved_input_edges(
        step=_step(step_order=2, input_source="previous_step"),
        source_text="",
        used_question_binding=False,
        prior_results=[],
        state=None,
    )

    assert edges == ()


def test_flow_input_edge_records_the_consumed_value_identity() -> None:
    edges = build_resolved_input_edges(
        step=_step(step_order=1, input_source="flow_input"),
        source_text="hello",
        used_question_binding=False,
        prior_results=[],
        state=None,
    )

    assert len(edges) == 1
    assert edges[0].source_kind == "flow_input"
    assert edges[0].value_byte_size == 5
    assert edges[0].value_sha256 is not None
    assert "hello" not in (edges[0].value_sha256 or "")


def test_all_previous_steps_records_one_edge_per_consumed_step_in_order() -> None:
    first = _result(step_order=1, attempt_no=1)
    second = _result(step_order=2, attempt_no=2)

    edges = build_resolved_input_edges(
        step=_step(step_order=3, input_source="all_previous_steps"),
        source_text="combined",
        used_question_binding=False,
        prior_results=[second, first],
        state=None,
    )

    assert [edge.source_step_order for edge in edges] == [1, 2]
    assert [edge.source_attempt_no for edge in edges] == [1, 2]
    assert all(edge.source_kind == "all_previous_steps" for edge in edges)


def test_all_previous_steps_excludes_steps_at_or_after_the_consumer() -> None:
    edges = build_resolved_input_edges(
        step=_step(step_order=2, input_source="all_previous_steps"),
        source_text="combined",
        used_question_binding=False,
        prior_results=[_result(step_order=1), _result(step_order=2)],
        state=None,
    )

    assert [edge.source_step_order for edge in edges] == [1]
