"""End-to-end planner-turn runner wiring the orchestrator v2 helpers.

The pipeline runs one planner LLM call plus up to
`MAX_ORCHESTRATOR_REPAIR_RETRIES` repair attempts and returns an
accepted `PlannerOutput` or a terminal `RejectionReason`. It does NOT
persist anything — the caller builds the post-LLM assistant / tool
conversation messages from the accepted output and then invokes
`dispatch_planner_action` (for ask/commit/confirm) or the proposal-
processor adapter (for propose_plan).

Separating run from dispatch keeps the conversation-increment shape
under the caller's control: the planner's action and its user-facing
payload are only known after the LLM has produced the final accepted
output, so the caller — which also owns SSE emission, locking, and
lease bookkeeping — must be the one to assemble the messages persisted
by `commit_turn`.

The retry loop is owned here because the repair helper is per-call and
the evaluator is stateless. Budget accounting:

- `repaired` outcome → consumed retry slot (decrement toward budget)
  and re-evaluate the repaired output against the same orchestration
  context.
- `not_repairable` outcome → terminal with the ORIGINAL rejection.
  The helper short-circuited without calling the LLM, so
  `llm_calls_made` is NOT bumped.
- `commit_drift_blocked` → terminal with the drift rejection.
  The LLM ran, so `llm_calls_made` IS bumped; drift is not a
  retry-eligible condition, so `repair_attempts` is NOT bumped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    PlannerOutput,
    RejectionReason,
    evaluate_planner_output,
    parse_planner_output,
)
from intric.flows.ai_builder.ai_builder_repair import (
    MAX_ORCHESTRATOR_REPAIR_RETRIES,
    CompletionMetadata,
    RepairOutcome,
    repair_planner_turn,
)

PipelineOutcomeKind = Literal["accepted", "rejected", "parse_failed"]


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """Outcome of running one planner turn + up to N repair attempts.

    `kind="accepted"`: the evaluator returned ``None`` on the final
    parsed output. `accepted_output` carries the parsed PlannerOutput.
    The caller inspects `accepted_output.planner_action.kind` to route:
    dispatch via `dispatch_planner_action` for ask_question /
    commit_architecture / confirm_requirements, or hand off to the
    proposal-processor adapter for propose_plan.

    `kind="rejected"`: `rejection` carries the terminal reason —
    either the initial non-eligible rejection, the last rejection
    after budget exhaustion, or a `repair_attempted_commit_drift`
    produced by a drifted repair output.

    `kind="parse_failed"`: the LLM returned a response that could not
    be parsed as a PlannerOutput (truncation, schema drift, malformed
    JSON). `final_completion` is populated so the caller can check
    `finish_reason == "length"` and surface the existing
    `planner_output_too_long` error code instead of a generic parse
    failure. `parse_error_raw` and `parse_error_message` carry the
    offending body and the validator message for telemetry.

    `llm_calls_made` counts every `acompletion` call including the
    initial turn. `repair_attempts` counts only the repair calls that
    returned a `repaired` outcome (consumed a retry slot); drift,
    non-repairable, and parse-failure outcomes do NOT consume a
    retry slot.
    """

    kind: PipelineOutcomeKind
    accepted_output: PlannerOutput | None = None
    rejection: RejectionReason | None = None
    llm_calls_made: int = 0
    repair_attempts: int = 0
    final_completion: CompletionMetadata | None = None
    parse_error_raw: str | None = None
    parse_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class _InitialCallOutcome:
    raw: str
    metadata: CompletionMetadata
    parsed: PlannerOutput | None
    parse_error: str | None


async def _call_planner(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    messages: list[dict[str, Any]],
) -> _InitialCallOutcome:
    response = await litellm_client.acompletion(
        model=litellm_model,
        messages=messages,
        **litellm_kwargs,
    )
    raw = response.choices[0].message.content or ""
    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    metadata = CompletionMetadata(
        finish_reason=getattr(choice, "finish_reason", None),
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=getattr(usage, "total_tokens", None) if usage else None,
    )
    try:
        parsed = parse_planner_output(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        return _InitialCallOutcome(
            raw=raw,
            metadata=metadata,
            parsed=None,
            parse_error=str(exc),
        )
    return _InitialCallOutcome(
        raw=raw,
        metadata=metadata,
        parsed=parsed,
        parse_error=None,
    )


async def run_planner_pipeline(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    base_messages: list[dict[str, Any]],
    orchestration_context: OrchestrationContext,
) -> PipelineOutcome:
    """Run one planner turn with a repair loop; return accepted/rejected.

    `base_messages` is the chat-completion message list the caller has
    already assembled (system prompt + prior conversation + current
    user turn). `orchestration_context` is the evaluator's per-turn
    context; the same context is re-used across repair attempts because
    the session state has not been persisted yet.

    On `accepted`, the caller must build the post-LLM assistant / tool
    conversation messages from `accepted_output` and then call
    `dispatch_planner_action(...)` (or the proposal-processor adapter
    for propose_plan) to persist the turn atomically.
    """
    prior_commit = orchestration_context.session_state.architecture_commit

    initial = await _call_planner(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        messages=base_messages,
    )
    llm_calls_made = 1
    repair_attempts = 0
    final_metadata = initial.metadata

    if initial.parsed is None:
        return PipelineOutcome(
            kind="parse_failed",
            llm_calls_made=llm_calls_made,
            repair_attempts=repair_attempts,
            final_completion=final_metadata,
            parse_error_raw=initial.raw,
            parse_error_message=initial.parse_error,
        )

    output: PlannerOutput = initial.parsed
    raw = initial.raw

    rejection = evaluate_planner_output(output, orchestration_context)

    while rejection is not None and repair_attempts < MAX_ORCHESTRATOR_REPAIR_RETRIES:
        repair_outcome: RepairOutcome = await repair_planner_turn(
            litellm_client=litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            base_messages=base_messages,
            failed_output_json=raw,
            rejection=rejection,
            prior_architecture_commit=prior_commit,
        )
        if repair_outcome.kind == "not_repairable":
            return PipelineOutcome(
                kind="rejected",
                rejection=rejection,
                llm_calls_made=llm_calls_made,
                repair_attempts=repair_attempts,
                final_completion=final_metadata,
            )
        llm_calls_made += 1
        assert repair_outcome.completion_metadata is not None
        final_metadata = repair_outcome.completion_metadata
        if repair_outcome.kind == "parse_failed":
            return PipelineOutcome(
                kind="parse_failed",
                llm_calls_made=llm_calls_made,
                repair_attempts=repair_attempts,
                final_completion=final_metadata,
                parse_error_raw=repair_outcome.parse_error_raw,
                parse_error_message=repair_outcome.parse_error_message,
            )
        if repair_outcome.kind == "commit_drift_blocked":
            return PipelineOutcome(
                kind="rejected",
                rejection=repair_outcome.drift_rejection,
                llm_calls_made=llm_calls_made,
                repair_attempts=repair_attempts,
                final_completion=final_metadata,
            )
        assert repair_outcome.repaired_output is not None
        output = repair_outcome.repaired_output
        raw = output.model_dump_json()
        repair_attempts += 1
        rejection = evaluate_planner_output(output, orchestration_context)

    if rejection is not None:
        return PipelineOutcome(
            kind="rejected",
            rejection=rejection,
            llm_calls_made=llm_calls_made,
            repair_attempts=repair_attempts,
            final_completion=final_metadata,
        )

    return PipelineOutcome(
        kind="accepted",
        accepted_output=output,
        llm_calls_made=llm_calls_made,
        repair_attempts=repair_attempts,
        final_completion=final_metadata,
    )


__all__ = [
    "PipelineOutcome",
    "run_planner_pipeline",
]
