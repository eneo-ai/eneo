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
    when the repaired output mutates the prior committed architecture's
    semantic body (`tuples_chain`, `chosen_patterns`,
    `required_capabilities`). A repaired delta that omits
    `architecture_commit` is preservation-by-absence, not drift — the
    evaluator only inspects the delta when it is populated. This is a
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

from intric.flows.ai_builder.ai_builder_ask_question_contract import (
    canonical_ask_question_targets,
    format_ask_question_targets,
)
from intric.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    assert_architecture_commit_draft_matches_pinned,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    CompletionMetadata,
    call_planner_completion,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    PlannerOutput,
    RejectionCode,
    RejectionReason,
    parse_planner_output,
    summarize_parse_failure,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
)

MAX_ORCHESTRATOR_REPAIR_RETRIES: Final[int] = 3

# Parse-repair is a separate budget from evaluator-repair because the
# failure domains are disjoint — a parse failure means the LLM produced
# bytes we could not turn into a PlannerOutput at all, so there is no
# evaluator context to preserve across retries. One corrective turn is
# enough in practice (the corrective prompt pastes the parse error back
# to the LLM); two+ retries start looking like a prose-mode model that
# cannot honor the contract, at which point falling through to the
# user-facing error is the honest move.
MAX_PARSE_REPAIR_RETRIES: Final[int] = 1


# Repair-eligible rejection codes. A rejection outside this set means
# the planner misunderstood a constraint that a corrective prompt cannot
# safely repair (e.g. invented an unsupported tuple). Vocabulary and
# action-loop drift are eligible because the safe remediation is an
# action pivot inside the same server-owned constraint surface.
#
# `architecture_commit_premature_unresolved_choices` is eligible
# because the remediation is an action pivot (commit → ask_question),
# not a re-emission of the same action honoring a different
# constraint. The corrective prompt names the pivot target
# explicitly via `_REPAIR_DIRECTIVES` below.
_REPAIR_ELIGIBLE_CODES: frozenset[RejectionCode] = frozenset(
    {
        "architecture_commit_premature_unresolved_choices",
        "architecture_commit_missing_delta",
        "off_topic_question",
        "duplicate_question",
    }
)


# Per-code remediation directive. The premature-commit directive tells
# the LLM to pivot to `ask_question` about one of the blocking slots
# instead of re-emitting `commit_architecture`.
_PREMATURE_COMMIT_DIRECTIVE: Final[str] = (
    "The valid next action is `ask_question` about one of the "
    "unresolved slots named above. Emit `planner_action` with "
    '`kind="ask_question"` and a `question_id` that targets one of '
    "those slots. Do NOT emit `commit_architecture` again this turn."
)
_PRESERVE_COMMIT_DIRECTIVE: Final[str] = (
    "Re-emit a planner JSON product that honors the constraint. Do "
    "NOT change the committed architecture."
)


def _off_topic_question_directive() -> str:
    return (
        "The valid next action is `ask_question`. Replace invented "
        "domain-specific identifiers with one of the allowed targets "
        "named in the rejection detail. Emit that target in both "
        "`payload.question_id` and `payload.slot_name`; keep any narrower "
        "domain concept in `payload.prompt` only. Canonical ask_question "
        "targets are: "
        f"{format_ask_question_targets(canonical_ask_question_targets())}."
    )


_DUPLICATE_QUESTION_DIRECTIVE: Final[str] = (
    "Do NOT repeat the same `ask_question`. Use the latest user message "
    "and conversation context as evidence. If the answer resolves the "
    "slot, emit a valid non-duplicate next action such as "
    "`confirm_requirements` or `commit_architecture` when all required "
    "choices are resolved. If more information is still needed, ask a "
    "different unresolved slot from the allowed target surface; do not "
    "re-ask the rejected question ID this turn."
)


_MISSING_COMMIT_DELTA_DIRECTIVE: Final[str] = (
    "If `planner_action.kind` is `commit_architecture`, keep "
    "`planning_state_delta.architecture_commit` as null; the server derives "
    "the architecture from resolved planning slots and the Flow Capability "
    "Manifest. Do NOT emit `architecture_hash` or `committed_at`. If this "
    "turn still lacks enough resolved state to commit, pivot to "
    "`ask_question` for the unresolved slot instead of re-emitting "
    "`commit_architecture`."
)


def _repair_directive_for(code: RejectionCode) -> str:
    if code == "architecture_commit_premature_unresolved_choices":
        return _PREMATURE_COMMIT_DIRECTIVE
    if code == "architecture_commit_missing_delta":
        return _MISSING_COMMIT_DELTA_DIRECTIVE
    if code == "off_topic_question":
        return _off_topic_question_directive()
    if code == "duplicate_question":
        return _DUPLICATE_QUESTION_DIRECTIVE
    return _PRESERVE_COMMIT_DIRECTIVE


def build_repair_user_message(*, rejection: RejectionReason) -> str:
    """Compose the corrective user-turn for a semantic-rejection repair.

    The repair prompt always echoes `rejection.detail` (never the
    `code`, which is internal vocabulary) and appends a per-code
    remediation directive. Extracted as a named function so new
    eligible codes land in one place with testable prompt text.
    """
    return (
        "The previous response was rejected because: "
        f"{rejection.detail}. {_repair_directive_for(rejection.code)}"
    )


def build_repair_messages(
    *,
    base_messages: list[dict[str, Any]],
    failed_output_json: str,
    rejection: RejectionReason,
) -> list[dict[str, Any]]:
    """Compose the full semantic-repair conversation.

    Kept separate from `repair_planner_turn` so the orchestration
    pipeline can use the same conversation as the base for parse-repair
    if the semantic-repair LLM call itself returns malformed JSON.
    """
    return [
        *base_messages,
        {"role": "assistant", "content": failed_output_json},
        {
            "role": "user",
            "content": build_repair_user_message(rejection=rejection),
        },
    ]


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
      prior committed architecture's semantic body. `drift_rejection`
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
    parse_failure_diagnostics: dict[str, Any] | None = None


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

    messages = build_repair_messages(
        base_messages=base_messages,
        failed_output_json=failed_output_json,
        rejection=rejection,
    )

    completion = await call_planner_completion(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        messages=messages,
    )
    raw_content = completion.raw_content
    completion_metadata = completion.metadata

    try:
        repaired_output = parse_planner_output(raw_content)
    except (ValidationError, json.JSONDecodeError) as exc:
        return RepairOutcome(
            kind="parse_failed",
            completion_metadata=completion_metadata,
            parse_error_raw=raw_content,
            parse_error_message=str(exc),
            parse_failure_diagnostics=summarize_parse_failure(raw_content, exc),
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


@dataclass(frozen=True, slots=True)
class ParseRepairOutcome:
    """Result of one parse-repair corrective LLM call.

    - `kind="repaired"`: the corrective call produced a parseable
      PlannerOutput. `repaired_output` + `completion_metadata` are
      populated. The caller re-enters the evaluator path with the
      repaired output — a repaired parse does NOT bypass invariant
      checks.
    - `kind="parse_failed"`: the corrective call still produced
      unparseable bytes. `completion_metadata`, `parse_error_raw`, and
      `parse_error_message` mirror the initial parse-failure surface
      so the outer loop can surface `finish_reason == "length"` (if
      the corrective turn got truncated) and log the sanitized parse
      diagnostics.
    """

    kind: Literal["repaired", "parse_failed"]
    repaired_output: PlannerOutput | None = None
    completion_metadata: CompletionMetadata | None = None
    parse_error_raw: str | None = None
    parse_error_message: str | None = None
    parse_failure_diagnostics: dict[str, Any] | None = None


def build_parse_repair_user_message(*, parse_error_message: str) -> str:
    """Compose the corrective user-turn for a parse-repair retry.

    Extracted to keep the prompt text testable and to land one place
    where layout reminders for observed confusion patterns
    accumulate. Keep this prompt tied to the active PlannerOutput
    schema only; proposal tool-call repair lives in the proposal
    processor, not in this planner-union repair helper.
    """
    return (
        "The previous response could not be parsed as a PlannerOutput "
        f"JSON object. Parser error: {parse_error_message}. Re-emit the "
        "response as a single raw JSON object matching the "
        "PlannerOutput schema. Do NOT wrap the JSON in markdown code "
        "fences. Do NOT add prose before or after the JSON. Do NOT "
        "invent keys not declared in the schema. Reminders: "
        "For `kind=commit_architecture`, prefer "
        "`architecture_commit: null`; the server derives the architecture "
        "from resolved planning slots and the Flow Capability Manifest. "
        "Do NOT emit `architecture_hash` or `committed_at`; the server "
        "owns those values."
    )


async def repair_parse_failure(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    base_messages: list[dict[str, Any]],
    failed_output_raw: str,
    parse_error_message: str,
) -> ParseRepairOutcome:
    """Run one corrective turn when the LLM produced unparseable bytes.

    The corrective conversation echoes the failed body back to the
    model and states the parse error verbatim (validator message or
    JSON-decode message). This is deliberate: empirically, showing
    the model its own malformed output next to the decoder's
    complaint is the single most effective correction signal. The
    corrective user-turn directive reminds the model of the shape
    contract — raw JSON object, no markdown fences, no prose.

    Unlike `repair_planner_turn`, there is no rejection code to gate
    on — a raw parse failure has no `RejectionReason`. The caller is
    responsible for skipping this helper when the failed completion
    was truncation (``finish_reason == "length"``), because a
    corrective turn would just be a second chance to be truncated.
    """
    messages: list[dict[str, Any]] = [
        *base_messages,
        {"role": "assistant", "content": failed_output_raw},
        {
            "role": "user",
            "content": build_parse_repair_user_message(
                parse_error_message=parse_error_message,
            ),
        },
    ]

    completion = await call_planner_completion(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        messages=messages,
    )
    raw_content = completion.raw_content
    completion_metadata = completion.metadata

    try:
        repaired_output = parse_planner_output(raw_content)
    except (ValidationError, json.JSONDecodeError) as exc:
        return ParseRepairOutcome(
            kind="parse_failed",
            completion_metadata=completion_metadata,
            parse_error_raw=raw_content,
            parse_error_message=str(exc),
            parse_failure_diagnostics=summarize_parse_failure(raw_content, exc),
        )

    return ParseRepairOutcome(
        kind="repaired",
        repaired_output=repaired_output,
        completion_metadata=completion_metadata,
    )


def _detect_commit_drift(
    *,
    prior: ArchitectureCommit | None,
    after: ArchitectureCommitDraft | None,
) -> RejectionReason | None:
    """Return a drift rejection if the repaired commit mutates the prior.

    Matches the evaluator's preservation-by-absence semantics: when a
    prior commit is pinned and the repaired delta omits
    `architecture_commit`, that is not drift. Only when the repaired
    output carries a delta commit do we invoke
    `assert_architecture_commit_unchanged` and classify hash or body
    divergence as drift. The exception message already names the
    offending field(s), so we forward it as the `RejectionReason.detail`
    the outer loop surfaces to telemetry.
    """
    if after is None:
        return None
    try:
        assert_architecture_commit_draft_matches_pinned(before=prior, after=after)
    except CommitDriftError as exc:
        return RejectionReason(
            code="repair_attempted_commit_drift",
            detail=str(exc),
        )
    return None


__all__ = [
    "MAX_ORCHESTRATOR_REPAIR_RETRIES",
    "MAX_PARSE_REPAIR_RETRIES",
    "ParseRepairOutcome",
    "RepairOutcome",
    "build_repair_messages",
    "build_parse_repair_user_message",
    "build_repair_user_message",
    "repair_parse_failure",
    "repair_planner_turn",
]
