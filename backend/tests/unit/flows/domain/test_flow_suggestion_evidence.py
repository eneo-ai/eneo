"""The content-free run evidence: what a call's tokens per byte are, what an
edge cost, which forwarding facts count as measured, and when a draft step
counts as changed since a version."""

from __future__ import annotations

from uuid import UUID

from eneo.flows.domain.flow_suggestion_evidence import (
    EvidenceAttempt,
    EvidenceCall,
    EvidenceEdge,
    RunEvidence,
    average_over_runs,
    step_definition_facts,
)
from eneo.flows.domain.forwarding_facts import (
    ForwardingFacts,
    not_measured_forwarding_facts,
)

_STEP = UUID(int=1)
_MODEL = UUID(int=900)


def _edge(size: int | None, *, ref: str = "input_source") -> EvidenceEdge:
    return EvidenceEdge(
        binding_ref=ref,
        source_step_id=_STEP,
        selector=("output", "text"),
        byte_size=size,
        sha256=None if size is None else "a" * 64,
    )


def _call(
    tokens: int | None, indexes: tuple[int, ...], *, status: str = "completed"
) -> EvidenceCall:
    return EvidenceCall(
        status=status,
        call_reason="initial",
        num_tokens_input=tokens,
        num_tokens_output=10 if tokens is not None else None,
        edge_indexes=indexes,
    )


def _attempt(
    edges, calls, forwarding: ForwardingFacts | None = None
) -> EvidenceAttempt:
    return EvidenceAttempt(
        step_id=_STEP,
        step_order=2,
        status="completed",
        error_code=None,
        edges=tuple(edges),
        calls=tuple(calls),
        forwarding=forwarding,
    )


def _facts(**changes):
    fields = {
        "input_source": "previous_step",
        "input_type": "text",
        "input_contract": None,
        "input_bindings": None,
        "input_config": None,
        "output_mode": "pass_through",
        "output_type": "text",
        "output_contract": None,
        "output_config": None,
        "prompt_text": "Sammanfatta.",
        "completion_model_id": _MODEL,
    }
    return step_definition_facts(**{**fields, **changes})


def test_tokens_per_byte_is_the_calls_input_over_the_bytes_it_sent() -> None:
    attempt = _attempt([_edge(1000), _edge(3000)], [_call(800, (0, 1))])

    assert attempt.tokens_per_byte(attempt.calls[0]) == 0.2


def test_a_call_that_did_not_complete_or_sent_no_measured_edge_has_no_rate() -> None:
    attempt = _attempt(
        [_edge(None), _edge(100)],
        [_call(None, (1,), status="rejected"), _call(50, (0,))],
    )

    assert attempt.tokens_per_byte(attempt.calls[0]) is None
    assert attempt.tokens_per_byte(attempt.calls[1]) is None


def test_an_edge_costs_its_bytes_at_the_rate_of_every_call_that_sent_it() -> None:
    # Two item calls send edge 0; the second call's rate is twice the first's.
    attempt = _attempt([_edge(100), _edge(100)], [_call(20, (0, 1)), _call(40, (0, 1))])

    assert attempt.edge_tokens(0) == (30.0, 2)
    assert attempt.edge_tokens(5) is None


def test_billed_tokens_and_peak_input_count_completed_calls_only() -> None:
    attempt = _attempt(
        [_edge(100)],
        [_call(70, (0,)), _call(90, (0,)), _call(None, (0,), status="rejected")],
    )

    assert attempt.billed_tokens() == 70 + 10 + 90 + 10
    assert attempt.peak_input_tokens() == 90


def test_only_facts_the_worker_measured_count_as_forwarding_facts() -> None:
    measured = ForwardingFacts(schema_version=1, measured=True, call_count=1)
    unmeasured = not_measured_forwarding_facts(reason="computation_failed")

    assert _attempt([], [], measured).measured_forwarding() == measured
    assert _attempt([], [], unmeasured).measured_forwarding() is None
    assert _attempt([], []).measured_forwarding() is None


def test_the_facts_describe_the_first_completed_call() -> None:
    attempt = _attempt(
        [_edge(100)],
        [_call(None, (0,), status="rejected"), _call(70, (0,)), _call(90, (0,))],
    )

    assert attempt.measured_call() == attempt.calls[1]
    assert (
        _attempt([_edge(100)], [_call(None, (0,), status="failed")]).measured_call()
        is None
    )


def test_the_facts_ignore_what_changes_no_measurement() -> None:
    base = _facts()

    assert _facts(input_config={}) == base
    assert _facts(input_config={"tool": {"pinned": True}}) == base
    assert (
        _facts(output_mode="template_fill", output_config={"a": 1}).definition_hash
        == _facts(output_mode="template_fill").definition_hash
    )


def test_the_facts_change_with_the_prompt_the_model_or_the_input() -> None:
    base = _facts()

    assert _facts(prompt_text="Sammanfatta kort.") != base
    assert _facts(completion_model_id=UUID(int=901)) != base
    assert _facts(input_source="all_previous_steps") != base


def test_a_step_is_changed_since_a_version_unless_its_facts_are_equal() -> None:
    evidence = RunEvidence(
        runs=(),
        published_steps={(1, _STEP): _facts(), (2, _STEP): _facts(prompt_text="Ny.")},
        draft_steps={_STEP: _facts()},
    )

    assert evidence.step_changed_since(_STEP, 1) is False
    assert evidence.step_changed_since(_STEP, 2) is True
    # A version that does not have the step proves nothing about it.
    assert evidence.step_changed_since(_STEP, 3) is True
    assert evidence.same_model_and_output(_STEP, 2) is True
    assert evidence.same_model_and_output(_STEP, 3) is False


def test_the_reasoning_effort_changes_no_facts_but_another_model_setup() -> None:
    evidence = RunEvidence(
        runs=(),
        published_steps={
            (1, _STEP): _facts(reasoning_effort="high"),
            (2, _STEP): _facts(reasoning_effort="low"),
        },
        draft_steps={_STEP: _facts(reasoning_effort="high")},
    )

    # What reaches the model is the same, so the step is unchanged since
    # either version; what its model writes depends on the effort.
    assert evidence.step_changed_since(_STEP, 2) is False
    assert evidence.same_model_setup(_STEP, 1) is True
    assert evidence.same_model_setup(_STEP, 2) is False
    assert _facts(reasoning_effort="").reasoning_effort is None


def test_an_average_names_its_run_count_and_newest_version() -> None:
    measurement = average_over_runs([(100.0, 2), (300.0, 3)])

    assert measurement is not None
    assert (measurement.average, measurement.run_count, measurement.version) == (
        200.0,
        2,
        3,
    )
    assert average_over_runs([]) is None
