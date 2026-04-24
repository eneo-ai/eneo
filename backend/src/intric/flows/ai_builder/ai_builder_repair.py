"""Single-pass planner repair helper.

When the orchestrator's guardrails reject a planner turn, the outer
`send_message` loop asks the planner to re-emit its JSON product with
the constraint honored. This module exposes a per-call helper the
outer loop invokes; the outer loop owns the retry budget.

The helper is deliberately narrow:

- It accepts one failed `PlannerOutput` + its `RejectionReason` and the
  session's `prior_architecture_commit` (if any).
- For rejection codes outside `_REPAIR_ELIGIBLE_CODES` it returns
  `RepairOutcome(kind="not_repairable")` without making an LLM call.
  Non-repair-eligible rejections need a fresh planner turn against a
  refreshed context, not a corrective prompt.
- For repair-eligible codes it synthesizes a corrective conversation:
  ``base_messages + [assistant-echo of failed_output] + [user-prompt
  with rejection.detail + preserve-architecture directive]``, calls the
  LLM once, parses the reply via `parse_planner_output`, and:
  * Returns `RepairOutcome(kind="commit_drift_blocked", ...)` with a
    new `RejectionReason(code="repair_attempted_commit_drift", ...)`
    when the repaired output mutates the prior `architecture_hash` or
    drops the commit entirely after a prior commit existed. This is a
    hard failure — the outer loop does NOT decrement its retry budget
    on drift because drift is not a retry-eligible condition.
  * Returns `RepairOutcome(kind="repaired", repaired_output=...)`
    otherwise. The outer loop re-runs `evaluate_planner_output` on the
    repaired output; if it still rejects, the outer loop calls this
    helper again with a decremented budget.

The rejection `code` itself is NEVER rendered into the repair prompt —
only `rejection.detail` reaches the LLM. Rejection codes are internal
vocabulary and surfacing them in prompts leaks the guardrail naming
scheme to the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    assert_architecture_commit_unchanged,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    PlannerOutput,
    RejectionCode,
    RejectionReason,
    parse_planner_output,
)
from intric.flows.ai_builder.planning_state import ArchitectureCommit

MAX_ORCHESTRATOR_REPAIR_RETRIES: Final[int] = 3


@dataclass(frozen=True, slots=True)
class CompletionMetadata:
    """Metadata from one LLM completion call.

    Surfaced on `RepairOutcome` so the outer pipeline can track the
    final call's metadata — the caller needs `finish_reason == "length"`
    to detect truncation and `*_tokens` for per-turn telemetry.
    Metadata is extracted BEFORE parse, so truncation that produced
    malformed JSON still surfaces as a `parse_failed` outcome with
    metadata populated.

    `None` fields are normal — upstream clients (litellm) may not
    populate every metric for every provider.
    """

    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


# Repair-eligible rejection codes. A rejection outside this set means
# the planner misunderstood the constraint surface (e.g. asked a
# duplicate question, invented an unsupported tuple) — a corrective
# prompt on top of the same turn context would re-inherit the same
# misunderstanding. The outer loop handles those by advancing the
# session to a fresh turn instead.
_REPAIR_ELIGIBLE_CODES: frozenset[RejectionCode] = frozenset(
    {
        "propose_plan_without_architecture_commit",
        "propose_plan_missing_draft_plan",
        "propose_plan_draft_plan_structural_mismatch",
    }
)


RepairOutcomeKind = Literal[
    "not_repairable",
    "repaired",
    "commit_drift_blocked",
    "parse_failed",
]


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """Result of one repair attempt.

    - `kind="not_repairable"`: the rejection was outside the eligible
      set. `repaired_output`, `drift_rejection`, `completion_metadata`,
      and the parse-error fields are all `None` (the helper
      short-circuited without calling the LLM).
    - `kind="repaired"`: LLM produced a valid PlannerOutput that did
      not drift the prior commit. `repaired_output` carries the new
      output; `completion_metadata` carries the LLM call's metadata.
      The outer loop must still re-run `evaluate_planner_output` on it.
    - `kind="commit_drift_blocked"`: the repaired output mutated the
      prior `architecture_hash` or dropped the commit. `drift_rejection`
      carries a `repair_attempted_commit_drift` reason the outer loop
      surfaces to telemetry; `completion_metadata` is populated because
      the LLM ran. The retry budget is NOT decremented.
    - `kind="parse_failed"`: the LLM's response was not a valid
      PlannerOutput JSON (truncation, schema drift, malformed payload).
      `completion_metadata` is populated — crucially so the outer loop
      can detect `finish_reason == "length"` and surface
      `planner_output_too_long` to the client. `parse_error_raw`
      carries the unparseable body and `parse_error_message` the
      validator's complaint string for telemetry.
    """

    kind: RepairOutcomeKind
    repaired_output: PlannerOutput | None = None
    drift_rejection: RejectionReason | None = None
    completion_metadata: CompletionMetadata | None = None
    parse_error_raw: str | None = None
    parse_error_message: str | None = None


async def repair_planner_turn(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    base_messages: list[dict[str, Any]],
    failed_output_json: str,
    rejection: RejectionReason,
    prior_architecture_commit: ArchitectureCommit | None,
) -> RepairOutcome:
    """Run one corrective turn against the planner LLM.

    `base_messages` is the same list of chat-completion messages the
    outer loop used for the rejected turn — the helper appends an
    assistant-echo of `failed_output_json` and a synthesized user turn
    so the LLM sees what it produced and why it was rejected.
    """
    if rejection.code not in _REPAIR_ELIGIBLE_CODES:
        return RepairOutcome(kind="not_repairable")

    messages: list[dict[str, Any]] = [
        *base_messages,
        {"role": "assistant", "content": failed_output_json},
        {
            "role": "user",
            "content": (
                "The previous response was rejected because: "
                f"{rejection.detail}. Re-emit a planner JSON product "
                "that honors the constraint. Do NOT change the "
                "committed architecture."
            ),
        },
    ]

    response = await litellm_client.acompletion(
        model=litellm_model,
        messages=messages,
        **litellm_kwargs,
    )
    raw_content = response.choices[0].message.content or ""
    completion_metadata = _extract_completion_metadata(response)

    try:
        repaired_output = parse_planner_output(raw_content)
    except (ValidationError, json.JSONDecodeError) as exc:
        return RepairOutcome(
            kind="parse_failed",
            completion_metadata=completion_metadata,
            parse_error_raw=raw_content,
            parse_error_message=str(exc),
        )

    drift = _detect_commit_drift(
        prior=prior_architecture_commit,
        after=repaired_output.planning_state_delta.architecture_commit,
    )
    if drift is not None:
        return RepairOutcome(
            kind="commit_drift_blocked",
            drift_rejection=drift,
            completion_metadata=completion_metadata,
        )

    return RepairOutcome(
        kind="repaired",
        repaired_output=repaired_output,
        completion_metadata=completion_metadata,
    )


def _extract_completion_metadata(response: Any) -> CompletionMetadata:
    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    return CompletionMetadata(
        finish_reason=getattr(choice, "finish_reason", None),
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=getattr(usage, "total_tokens", None) if usage else None,
    )


def _detect_commit_drift(
    *,
    prior: ArchitectureCommit | None,
    after: ArchitectureCommit | None,
) -> RejectionReason | None:
    """Return a drift rejection if the repaired commit mutates the prior.

    Matches the evaluator's preservation-by-absence semantics: when a
    prior commit is pinned and the repaired delta omits
    `architecture_commit`, that is not drift — the knowledge-pack
    protocol teaches the planner to populate `architecture_commit` only
    on `commit_architecture` turns, so a repaired `propose_plan` is
    allowed (and expected) to leave the field ``None``. Only when the
    repaired output carries a delta commit do we invoke
    `assert_architecture_commit_unchanged` and classify hash or body
    divergence as drift. The exception message already names the
    offending field(s), so we forward it as the `RejectionReason.detail`
    the outer loop surfaces to telemetry.
    """
    if after is None:
        return None
    try:
        assert_architecture_commit_unchanged(before=prior, after=after)
    except CommitDriftError as exc:
        return RejectionReason(
            code="repair_attempted_commit_drift",
            detail=str(exc),
        )
    return None


__all__ = [
    "MAX_ORCHESTRATOR_REPAIR_RETRIES",
    "CompletionMetadata",
    "RepairOutcome",
    "repair_planner_turn",
]
