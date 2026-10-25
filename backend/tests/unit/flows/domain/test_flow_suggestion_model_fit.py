"""``oversized_reasoning``: high reasoning effort on a step whose runs show
a small structured extraction, judged from the catalogue's facts and the
measured calls; its thresholds and how its runs are counted."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from eneo.flows.domain.flow_suggestion_evidence import EvidenceAttempt
from eneo.flows.domain.flow_suggestion_model_fit import (
    OVERSIZED_REASONING_MAX_INPUT_TOKENS,
    OVERSIZED_REASONING_MAX_OUTPUT_TOKENS,
)
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionStep,
    suggestion_fingerprint,
)
from tests.unit.flows.domain.suggestion_evidence_builders import (
    IDS,
    MODEL,
    analyzed,
    make_attempt,
    make_call,
    make_edge,
    make_facts,
    make_step,
)

_CONTRACT = {
    "type": "object",
    "properties": {"diarienummer": {"type": "string"}},
    "required": ["diarienummer"],
}
_LIMIT = 128_000


def _flow(**step2: Any) -> list[SuggestionStep]:
    """Step 2 extracts a JSON result from step 1."""
    columns: dict[str, Any] = {"output_type": "json", "output_contract": _CONTRACT}
    return [make_step(1), make_step(2, **{**columns, **step2})]


def _attempt(inputs: int = 1200, output: int = 900) -> EvidenceAttempt:
    return make_attempt(
        2, [make_edge("input_source", 1)], [make_call(inputs, (0,), output=output)]
    )


def _oversized(
    runs: Sequence[Sequence[EvidenceAttempt]],
    *,
    steps: Sequence[SuggestionStep] | None = None,
    effort: str | None = "high",
    reasoning: bool = True,
    limit: int | None = _LIMIT,
    **kwargs: Any,
) -> list[FlowSuggestion]:
    steps = steps or _flow()
    return analyzed(
        steps,
        runs,
        FlowSuggestionCode.OVERSIZED_REASONING,
        draft={IDS[2]: make_facts(output_type="json", reasoning_effort=effort)},
        reasoning_models=frozenset({MODEL}) if reasoning else frozenset(),
        limit=limit,
        **kwargs,
    )


def test_high_effort_on_a_small_extraction_is_oversized_reasoning() -> None:
    (item,) = _oversized([[_attempt()]])

    assert item.steps == (IDS[2],)
    assert item.params == {
        "reasoning_effort": "high",
        "peak_input_tokens": 1200,
        "token_limit": _LIMIT,
        "limit_share": 0.01,
        "peak_output_tokens": 900,
        "run_count": 1,
        "held_runs": 1,
    }
    assert item.impact.basis == "runs"
    assert item.impact.level == "low"
    # The runs do not tell the reasoning apart from the answer.
    assert item.impact.tokens_per_run is None
    assert item.impact.run_count == 1
    assert item.impact.step_changed_since is False
    assert item.fix.kind == "advice"
    assert item.fingerprint == suggestion_fingerprint(
        FlowSuggestionCode.OVERSIZED_REASONING, [IDS[2]], {}
    )
    assert item.message == (
        "In 1 of the last 1 runs, step 2 asked its model for high reasoning "
        "effort to write a JSON result, and each call took at most 1200 input "
        "tokens (1 % of the model's limit) and wrote at most 900 output "
        "tokens, reasoning included; an extraction this small rarely needs "
        "that effort."
    )


def test_the_top_efforts_count_as_high_and_the_others_do_not() -> None:
    for effort in ("high", "xhigh", "max"):
        assert len(_oversized([[_attempt()]], effort=effort)) == 1, effort
    for effort in ("medium", "low", "minimal", "none", None):
        assert _oversized([[_attempt()]], effort=effort) == [], effort


def test_a_model_the_catalogue_does_not_mark_as_reasoning_is_skipped() -> None:
    assert _oversized([[_attempt()]], reasoning=False) == []


def test_only_a_structured_extraction_with_a_known_limit_is_judged() -> None:
    text = _flow(output_type="text", output_contract=None)
    no_contract = _flow(output_contract=None)

    assert _oversized([[_attempt()]], steps=text) == []
    assert _oversized([[_attempt()]], steps=no_contract) == []
    assert _oversized([[_attempt()]], limit=None) == []


def test_the_input_bound_is_a_share_of_the_limit_and_at_most_a_cap() -> None:
    # A tenth of a 20 000 token limit.
    assert len(_oversized([[_attempt(inputs=2000)]], limit=20_000)) == 1
    assert _oversized([[_attempt(inputs=2001)]], limit=20_000) == []
    # A tenth of a large limit is more than the cap.
    cap = OVERSIZED_REASONING_MAX_INPUT_TOKENS
    assert len(_oversized([[_attempt(inputs=cap)]], limit=1_000_000)) == 1
    assert _oversized([[_attempt(inputs=cap + 1)]], limit=1_000_000) == []


def test_the_output_bound_includes_the_reasoning() -> None:
    most = OVERSIZED_REASONING_MAX_OUTPUT_TOKENS

    assert len(_oversized([[_attempt(output=most)]])) == 1
    assert _oversized([[_attempt(output=most + 1)]]) == []


def test_the_calls_were_small_in_half_of_the_counted_runs() -> None:
    small, large = _attempt(), _attempt(output=20_000)

    (item,) = _oversized([[small], [large]])

    assert (item.params["run_count"], item.params["held_runs"]) == (2, 1)
    assert item.impact.run_count == 2
    assert _oversized([[small], [large], [large]]) == []


def test_runs_without_a_measured_call_or_with_another_effort_do_not_count() -> None:
    unmeasured = [
        # No token counts, a call that did not complete, and no call at all.
        make_attempt(2, [make_edge("input_source", 1)], [make_call(None, (0,))]),
        make_attempt(
            2,
            [make_edge("input_source", 1)],
            [make_call(1200, (0,), output=900, status="failed")],
        ),
        make_attempt(2),
    ]
    (item,) = _oversized(
        [[_attempt()], *([attempt] for attempt in unmeasured)],
    )
    assert item.params["run_count"] == 1

    # The measured version asked for a lower effort: its output says nothing
    # of what the effort asked for now writes.
    lower = {IDS[2]: make_facts(output_type="json", reasoning_effort="low")}
    assert _oversized([[_attempt()]], published=lower) == []
