"""Suggestions about how a step uses its model, measured against what the
model catalogue knows of the model.

``oversized_reasoning``: a step that asks its model for high reasoning
effort to write a small JSON result from a small input. Judged from facts
only: the catalogue marks the draft step's model as reasoning-capable and
knows its input limit, the step's assistant asks for an effort among
``HIGH_REASONING_EFFORTS``, the step writes a JSON result with an output
contract (a structured extraction), and in the counted runs its calls were
small. No price, no model name and no text of a run is read.

Small is the largest completed call of the run's attempt: an input of at
most ``OVERSIZED_REASONING_MAX_INPUT_SHARE`` of the model's input limit and
at most ``OVERSIZED_REASONING_MAX_INPUT_TOKENS``, and an output of at most
``OVERSIZED_REASONING_MAX_OUTPUT_TOKENS``. A call's output tokens include
what the model spent reasoning, so the output bound holds the answer and the
reasoning together: the rule reports a step whose whole call stayed small,
never one that reasoned at length, and it puts no number on what a lower
effort saves (the runs do not tell the reasoning apart from the answer).

What a run counts for: a run whose version gave the step the model, output
type and reasoning effort it has now, in which the step's attempt has a
completed call that reported both token counts. The finding is reported
when its calls were small in ``OVERSIZED_REASONING_MIN_RUN_SHARE`` or more
of those runs, as the other measured rules count.
"""

from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow_suggestion_evidence import EvidenceAttempt, RunEvidence
from eneo.flows.domain.flow_suggestion_input_rules import contract_fields
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionImpact,
    SuggestionStep,
    make_suggestion,
    uses_completion_model,
)

# The reasoning efforts that count as high: the top of the scale a model
# offers (`low`, `medium`, `high`, and where offered `xhigh` and `max`).
HIGH_REASONING_EFFORTS = frozenset({"high", "xhigh", "max"})
# A small input: at most this share of the model's input token limit ...
OVERSIZED_REASONING_MAX_INPUT_SHARE = 0.1
# ... and at most this many tokens, whatever the limit.
OVERSIZED_REASONING_MAX_INPUT_TOKENS = 8_000
# A small output: at most this many tokens, the reasoning included.
OVERSIZED_REASONING_MAX_OUTPUT_TOKENS = 4_000
# Reported when the calls were small in at least this share of the counted
# runs.
OVERSIZED_REASONING_MIN_RUN_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class _Calls:
    """The largest completed call of one attempt."""

    input_tokens: int
    output_tokens: int


def _largest_calls(attempt: EvidenceAttempt) -> _Calls | None:
    measured = [
        (call.num_tokens_input, call.num_tokens_output)
        for call in attempt.calls
        if call.completed
        and call.num_tokens_input is not None
        and call.num_tokens_output is not None
    ]
    if not measured:
        return None
    return _Calls(
        input_tokens=max(tokens for tokens, _ in measured),
        output_tokens=max(tokens for _, tokens in measured),
    )


def oversized_reasoning(
    draft: DraftReads, evidence: RunEvidence
) -> list[FlowSuggestion]:
    """``oversized_reasoning`` for every model step of the draft that asks
    for high reasoning effort while its counted runs show a small
    structured extraction; see the module docstring."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        facts = evidence.draft_steps.get(step.id)
        model_id = facts.completion_model_id if facts is not None else None
        if (
            facts is None
            or model_id is None
            or not uses_completion_model(step)
            or not contract_fields(step)
            or facts.reasoning_effort not in HIGH_REASONING_EFFORTS
            or model_id not in evidence.reasoning_models
        ):
            continue
        limit = evidence.model_input_limits.get(model_id)
        if limit is None or limit <= 0:
            continue
        max_input = min(
            OVERSIZED_REASONING_MAX_INPUT_SHARE * limit,
            OVERSIZED_REASONING_MAX_INPUT_TOKENS,
        )
        versions: list[int] = []
        held: list[_Calls] = []
        for run in evidence.runs:
            attempt = run.attempt(step.id)
            if attempt is None or not evidence.same_model_setup(step.id, run.version):
                continue
            calls = _largest_calls(attempt)
            if calls is None:
                continue
            versions.append(run.version)
            if (
                calls.input_tokens <= max_input
                and calls.output_tokens <= OVERSIZED_REASONING_MAX_OUTPUT_TOKENS
            ):
                held.append(calls)
        if not held or len(held) < OVERSIZED_REASONING_MIN_RUN_SHARE * len(versions):
            continue
        suggestions.append(
            _suggestion(
                step,
                effort=str(facts.reasoning_effort),
                limit=limit,
                held=held,
                versions=versions,
                evidence=evidence,
            )
        )
    return suggestions


def _suggestion(
    step: SuggestionStep,
    *,
    effort: str,
    limit: int,
    held: list[_Calls],
    versions: list[int],
    evidence: RunEvidence,
) -> FlowSuggestion:
    peak_input = max(calls.input_tokens for calls in held)
    peak_output = max(calls.output_tokens for calls in held)
    version = max(versions)
    share = peak_input / limit
    return make_suggestion(
        FlowSuggestionCode.OVERSIZED_REASONING,
        steps=(step.id,),
        premise={},
        params={
            "reasoning_effort": effort,
            "peak_input_tokens": peak_input,
            "token_limit": limit,
            "limit_share": round(share, 2),
            "peak_output_tokens": peak_output,
            "run_count": len(versions),
            "held_runs": len(held),
        },
        message=(
            f"In {len(held)} of the last {len(versions)} runs, step "
            f"{step.step_order} asked its model for {effort} reasoning effort to "
            f"write a JSON result, and each call took at most {peak_input} input "
            f"tokens ({_percent(share)} of the model's limit) and wrote at most "
            f"{peak_output} output tokens, reasoning included; an extraction "
            "this small rarely needs that effort."
        ),
        level="low",
        fix=FlowSuggestionFix(kind="advice"),
        impact=FlowSuggestionImpact(
            basis="runs",
            level="low",
            run_count=len(versions),
            version=version,
            step_changed_since=evidence.step_changed_since(step.id, version),
        ),
    )


def _percent(share: float) -> str:
    percent = round(100 * share)
    return f"{percent} %" if percent >= 1 else "under 1 %"


__all__ = [
    "HIGH_REASONING_EFFORTS",
    "OVERSIZED_REASONING_MAX_INPUT_SHARE",
    "OVERSIZED_REASONING_MAX_INPUT_TOKENS",
    "OVERSIZED_REASONING_MAX_OUTPUT_TOKENS",
    "OVERSIZED_REASONING_MIN_RUN_SHARE",
    "oversized_reasoning",
]
