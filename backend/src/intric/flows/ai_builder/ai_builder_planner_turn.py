"""Production glue: run one planner turn and persist its action.

`run_planner_turn` composes the orchestrator v2 stack into the shape
the builder's request-handling code needs per turn:

1. Call `run_planner_pipeline` for one structured-JSON LLM call, the
   monotonicity guardrails, and the per-call repair loop.
2. On accepted, route the action through `dispatch_planner_action` so
   the conversation append + `PlanningState` save happen atomically.
3. Return a `PlannerTurnResult` the caller pattern-matches on to emit
   SSE events, log telemetry, and surface terminal errors.

The helper is the ONLY module that bridges pipeline → dispatcher. It
does NOT emit SSE, manage session locks, or render assistant messages
— those are concerns of the caller (`AIBuilderPlanner.send_message`).
Keeping the bridge pure means tests exercise it with `AsyncMock(repo)`
+ a litellm-shaped stub, and future call sites reuse the same contract
without re-implementing the accept-and-dispatch dance.

Plan proposal no longer flows through this planner union. The caller
enters a separate proposal task after the server-owned action policy
selects that phase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from intric.flows.ai_builder.ai_builder_dispatcher import (
    PlannerDispatchResult,
    dispatch_planner_action,
)
from intric.flows.ai_builder.ai_builder_orchestration_pipeline import (
    PipelineOutcome,
    run_planner_pipeline,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    CommitArchitectureAction,
    OrchestrationContext,
    PlannerOutput,
    RejectionReason,
    evaluate_planner_output,
)
from intric.flows.ai_builder.ai_builder_repair import CompletionMetadata
from intric.flows.ai_builder.ai_builder_response_format import (
    PlannerResponseFormatSelection,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
    from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from intric.flows.domain.flow import Flow


PlannerTurnOutcomeKind = Literal[
    "dispatched",
    "rejected",
    "parse_failed",
]


@dataclass(frozen=True, slots=True)
class TurnTelemetry:
    """Per-turn observability record attached to every outcome.

    Captures what the caller needs for logs, SSE telemetry frames, and
    the session-level aggregator (`ai_builder_telemetry.summarize_session_telemetry`).

    `wall_clock_ms` is the end-to-end turn duration measured around the
    pipeline + dispatcher composition; on v2 this is dominated by LLM
    latency so we do not separate a per-call timing yet. `llm_calls_made`
    and `repair_attempts` are forwarded from `PipelineOutcome` unchanged.

    `architecture_commit_populated` is the per-turn rate signal the
    metric contract requires: `True` iff the turn was a successfully
    dispatched `commit_architecture` action. It is NOT set when the
    session already had a committed architecture and the planner
    proposed a plan against it — that turn neither populates nor
    changes the commit, so the rate tracks freshly-persisted commits
    only.
    """

    request_id: str | None
    model: str
    outcome_kind: PlannerTurnOutcomeKind
    wall_clock_ms: int
    llm_calls_made: int
    repair_attempts: int
    architecture_commit_populated: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    token_usage_source: str | None = None
    token_usage_estimated: bool = False
    parse_repair_attempts: int = 0


@dataclass(frozen=True, slots=True)
class PlannerTurnResult:
    """Caller-facing outcome of one planner turn.

    - `dispatched` — `accepted_output` + `dispatch_result` are both
      populated. The caller reads `dispatch_result.action_kind` to emit
      the right SSE event and `new_planning_state_version` so clients
      can discard stale local state.
    - `rejected` — terminal rejection from the pipeline's retry loop
      (monotonicity violation, architecture guard, or exhausted repair
      budget). `rejection` is populated; nothing was persisted.
    - `parse_failed` — pipeline could not parse the LLM response as a
      `PlannerOutput`. `final_completion` is populated so the caller
      can distinguish truncation (`finish_reason == "length"`) from
      other parse failures. `parse_error_raw` and `parse_error_message`
      carry the unparseable body and the validator complaint string.
    `llm_calls_made` / `repair_attempts` mirror the pipeline counters
    so the caller's telemetry does not have to reach back into the
    outcome's `PipelineOutcome`.
    """

    kind: PlannerTurnOutcomeKind
    turn_telemetry: TurnTelemetry
    accepted_output: PlannerOutput | None = None
    dispatch_result: PlannerDispatchResult | None = None
    rejection: RejectionReason | None = None
    final_completion: CompletionMetadata | None = None
    parse_error_raw: str | None = None
    parse_error_message: str | None = None
    parse_failure_diagnostics: dict[str, Any] | None = None
    llm_calls_made: int = 0
    repair_attempts: int = 0
    parse_repair_attempts: int = 0


def build_planner_litellm_kwargs(
    *,
    litellm_kwargs: dict[str, Any],
    max_tokens: int,
    temperature: float,
    response_format_selection: PlannerResponseFormatSelection,
) -> dict[str, Any]:
    return {
        **litellm_kwargs,
        **response_format_selection.litellm_kwargs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "drop_params": True,
    }


async def run_planner_turn(
    *,
    repo: "AIBuilderRepository",
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    turn: SessionSendTurn,
    flow: "Flow | None",
    base_messages: list[dict[str, Any]],
    orchestration_context: OrchestrationContext,
    build_new_messages: Callable[
        [PlannerOutput, TurnTelemetry], "list[ConversationMessage]"
    ],
    precomputed_output: PlannerOutput | None = None,
    telemetry_now_ms: Callable[[], int] | None = None,
) -> PlannerTurnResult:
    """Run one planner turn end-to-end and persist the result.

    Preconditions: `base_messages` is the chat-completion message list
    the caller has already assembled (system prompt + prior messages
    + current user turn). `build_new_messages` is called AFTER the
    pipeline accepts a `PlannerOutput`; the caller materializes the
    full conversation delta to persist (user turn + assistant turn
    rendered from the accepted action) so both land in the same
    atomic `commit_turn` savepoint. Building post-accept is the only
    way to include an assistant turn shaped from the LLM's answer
    without a second write.

    On `dispatched`, the dispatcher has already invoked
    `repo.commit_turn` in a savepoint; the caller does NOT need to
    commit again. On every other outcome, NO repo write has happened
    and `build_new_messages` was NOT called.

    `telemetry_now_ms` is an injectable millisecond clock used for
    `wall_clock_ms`; defaults to a `time.perf_counter`-based source.
    Tests override it to assert deterministic timings; production
    callers omit it.
    """
    now_ms = telemetry_now_ms if telemetry_now_ms is not None else _default_now_ms
    turn_started_ms = now_ms()

    if precomputed_output is None:
        pipeline_outcome: PipelineOutcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            base_messages=base_messages,
            orchestration_context=orchestration_context,
        )
    else:
        rejection = evaluate_planner_output(precomputed_output, orchestration_context)
        pipeline_outcome = (
            PipelineOutcome(
                kind="rejected",
                rejection=rejection,
            )
            if rejection is not None
            else PipelineOutcome(
                kind="accepted",
                accepted_output=precomputed_output,
            )
        )

    def _telemetry(
        outcome_kind: PlannerTurnOutcomeKind,
        *,
        architecture_commit_populated: bool,
    ) -> TurnTelemetry:
        completion = pipeline_outcome.final_completion
        cumulative_usage = pipeline_outcome.cumulative_token_usage
        return TurnTelemetry(
            request_id=str(turn.lease.request_id),
            model=litellm_model,
            outcome_kind=outcome_kind,
            wall_clock_ms=max(0, now_ms() - turn_started_ms),
            llm_calls_made=pipeline_outcome.llm_calls_made,
            repair_attempts=pipeline_outcome.repair_attempts,
            parse_repair_attempts=pipeline_outcome.parse_repair_attempts,
            architecture_commit_populated=architecture_commit_populated,
            prompt_tokens=(
                cumulative_usage.prompt_tokens
                if cumulative_usage is not None and cumulative_usage.has_tokens
                else completion.prompt_tokens
                if completion is not None
                else None
            ),
            completion_tokens=(
                cumulative_usage.completion_tokens
                if cumulative_usage is not None and cumulative_usage.has_tokens
                else completion.completion_tokens
                if completion is not None
                else None
            ),
            total_tokens=(
                cumulative_usage.total_tokens
                if cumulative_usage is not None and cumulative_usage.has_tokens
                else completion.total_tokens
                if completion is not None
                else None
            ),
            finish_reason=completion.finish_reason if completion is not None else None,
            token_usage_source=(
                cumulative_usage.source
                if cumulative_usage is not None and cumulative_usage.has_tokens
                else completion.token_usage_source
                if completion is not None
                else None
            ),
            token_usage_estimated=(
                cumulative_usage.estimated
                if cumulative_usage is not None and cumulative_usage.has_tokens
                else completion.token_usage_estimated
                if completion is not None
                else False
            ),
        )

    if pipeline_outcome.kind == "parse_failed":
        return PlannerTurnResult(
            kind="parse_failed",
            final_completion=pipeline_outcome.final_completion,
            parse_error_raw=pipeline_outcome.parse_error_raw,
            parse_error_message=pipeline_outcome.parse_error_message,
            parse_failure_diagnostics=pipeline_outcome.parse_failure_diagnostics,
            llm_calls_made=pipeline_outcome.llm_calls_made,
            repair_attempts=pipeline_outcome.repair_attempts,
            parse_repair_attempts=pipeline_outcome.parse_repair_attempts,
            turn_telemetry=_telemetry(
                "parse_failed", architecture_commit_populated=False
            ),
        )
    if pipeline_outcome.kind == "rejected":
        return PlannerTurnResult(
            kind="rejected",
            rejection=pipeline_outcome.rejection,
            final_completion=pipeline_outcome.final_completion,
            llm_calls_made=pipeline_outcome.llm_calls_made,
            repair_attempts=pipeline_outcome.repair_attempts,
            parse_repair_attempts=pipeline_outcome.parse_repair_attempts,
            turn_telemetry=_telemetry("rejected", architecture_commit_populated=False),
        )

    assert pipeline_outcome.accepted_output is not None
    accepted = pipeline_outcome.accepted_output

    dispatched_telemetry = _telemetry(
        "dispatched",
        architecture_commit_populated=isinstance(
            accepted.planner_action, CommitArchitectureAction
        ),
    )

    new_messages = build_new_messages(accepted, dispatched_telemetry)
    dispatch_result = await dispatch_planner_action(
        repo=repo,
        turn=turn,
        output=accepted,
        new_messages=new_messages,
        flow=flow,
    )

    return PlannerTurnResult(
        kind="dispatched",
        accepted_output=accepted,
        dispatch_result=dispatch_result,
        final_completion=pipeline_outcome.final_completion,
        llm_calls_made=pipeline_outcome.llm_calls_made,
        repair_attempts=pipeline_outcome.repair_attempts,
        parse_repair_attempts=pipeline_outcome.parse_repair_attempts,
        turn_telemetry=dispatched_telemetry,
    )


def _default_now_ms() -> int:
    return int(time.perf_counter() * 1000)


__all__ = [
    "PlannerTurnOutcomeKind",
    "PlannerTurnResult",
    "TurnTelemetry",
    "build_planner_litellm_kwargs",
    "run_planner_turn",
]
