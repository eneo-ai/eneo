"""AI Builder orchestrator — structured JSON contract for the planner turn.

Every planner turn emits one JSON product with two halves:

- `planning_state_delta` — what the planner understood (signals added,
  slots resolved, optional architecture commit, optional draft plan).
  The delta carries `base_planning_state_version` so the repo's
  optimistic-concurrency guard can reject stale writes.
- `planner_action` — what the planner wants to do next. A discriminated
  union on `kind`: `ask_question`, `commit_architecture`,
  `confirm_requirements`, `propose_plan`.

`evaluate_planner_output` runs the monotonicity guardrails and returns a
`RejectionReason` the planner retry loop can consume, or ``None`` when
the turn is accepted. Action dispatch and atomic persistence are
caller responsibilities — see `ai_builder_dispatcher` and
`ai_builder_planner_turn`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, ValidationError

from intric.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    assert_architecture_commit_unchanged,
)
from intric.flows.ai_builder.ai_builder_event_models import KeyDecisionPayload
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
)
from intric.flows.enums import FlowInputType, FlowOutputMode, FlowOutputType
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    supports_step_io_tuple,
)


class _OrchestratorModel(BaseModel):
    """Strict base for orchestrator I/O models.

    `extra="forbid"` catches planner drift at parse time — the most
    common failure mode is the LLM inventing new keys.
    """

    model_config = ConfigDict(extra="forbid")


class DraftPlanEnvelope(_OrchestratorModel):
    """Top-level envelope for a planner-proposed draft plan.

    The fine-grained shape of `steps` and `form_fields` lands with the
    materialization bridge and its consumers. The envelope here is
    strict so the orchestrator rejects invented top-level keys, which
    are the drift the planner hits first when the LLM hallucinates a
    "plan_rationale" or "summary" sibling.
    """

    plan_id: Optional[str] = None
    steps: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    form_fields: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class PlanningStateDelta(_OrchestratorModel):
    base_planning_state_version: NonNegativeInt
    signals_added: list[PlanningSignal] = Field(default_factory=list[PlanningSignal])
    slots_resolved: list[ResolvedSlot] = Field(default_factory=list[ResolvedSlot])
    architecture_commit: Optional[ArchitectureCommit] = None
    draft_plan: Optional[DraftPlanEnvelope] = None


class AskQuestionPayload(_OrchestratorModel):
    question_id: str
    slot_name: str
    prompt: str


class CommitArchitecturePayload(_OrchestratorModel):
    note: str = ""


class ConfirmRequirementsPayload(_OrchestratorModel):
    summary: str
    key_decisions: list[KeyDecisionPayload] = Field(
        default_factory=list[KeyDecisionPayload]
    )
    input_description: str = ""
    output_description: str = ""
    assumptions: list[str] = Field(default_factory=list[str])
    manual_setup_notes: list[str] = Field(default_factory=list[str])


class ProposePlanPayload(_OrchestratorModel):
    plan_reference: str = "latest"


class AskQuestionAction(_OrchestratorModel):
    kind: Literal["ask_question"]
    payload: AskQuestionPayload


class CommitArchitectureAction(_OrchestratorModel):
    kind: Literal["commit_architecture"]
    payload: CommitArchitecturePayload


class ConfirmRequirementsAction(_OrchestratorModel):
    kind: Literal["confirm_requirements"]
    payload: ConfirmRequirementsPayload


class ProposePlanAction(_OrchestratorModel):
    kind: Literal["propose_plan"]
    payload: ProposePlanPayload


PlannerAction = Annotated[
    Union[
        AskQuestionAction,
        CommitArchitectureAction,
        ConfirmRequirementsAction,
        ProposePlanAction,
    ],
    Field(discriminator="kind"),
]


class PlannerOutput(_OrchestratorModel):
    planning_state_delta: PlanningStateDelta
    planner_action: PlannerAction


def parse_planner_output(raw: str | dict[str, Any]) -> PlannerOutput:
    """Parse a planner turn's JSON product into a typed PlannerOutput.

    Accepts either a JSON string or an already-decoded dict so callers
    can plumb through whatever their LLM transport hands back. Raises
    `pydantic.ValidationError` on any shape violation — unknown keys,
    unknown action kinds, negative version stamps, or payload shapes
    that don't match the declared `kind`.

    When the input is a string, an exact whole-response markdown code
    fence (``` ``` ```json\\n...\\n``` ``` ``` or ``` ``` ```\\n...\\n``` ```)
    is unwrapped first. This matches a real failure mode — some models
    wrap their JSON response in a fenced block despite JSON-mode being
    requested. Partial fences inside prose are NOT extracted: the strict
    contract is "one JSON object per turn," and extracting from prose
    would let a rationale block be accepted as the planner output.
    """
    if isinstance(raw, str):
        payload = json.loads(_unwrap_json_fence(raw))
    else:
        payload = raw
    return PlannerOutput.model_validate(payload)


_JSON_FENCE_LANG_PREFIX = "```json"
_JSON_FENCE_BARE_PREFIX = "```"
_JSON_FENCE_SUFFIX = "```"


def _unwrap_json_fence(raw: str) -> str:
    """Strip an exact whole-response markdown code fence, if present.

    Accepts ``` ``` ```json\\n{...}\\n``` ``` ``` and the language-less
    ``` ``` ```\\n{...}\\n``` ``` ``` shape after whitespace trim. Any
    other position of the fence tokens leaves `raw` unchanged — we do
    NOT extract the first fenced region from inside prose, because the
    model could echo an example payload as a rationale and a greedy
    extractor would accept it as the real planner output.
    """
    stripped = raw.strip()
    if not stripped.startswith(_JSON_FENCE_BARE_PREFIX):
        return raw
    if not stripped.endswith(_JSON_FENCE_SUFFIX):
        return raw
    if stripped.startswith(_JSON_FENCE_LANG_PREFIX):
        body = stripped[len(_JSON_FENCE_LANG_PREFIX) : -len(_JSON_FENCE_SUFFIX)]
    else:
        body = stripped[len(_JSON_FENCE_BARE_PREFIX) : -len(_JSON_FENCE_SUFFIX)]
    return body.strip()


def summarize_parse_failure(raw: str, exc: Exception) -> dict[str, Any]:
    """Build a privacy-safe diagnostic summary of a parse failure.

    Callers use this to log what went wrong WITHOUT emitting the raw
    LLM body. Raw bodies may carry user prompts, attachment-derived
    content, or PII; we fingerprint instead of logging.

    Returned keys:

    - `parse_error_kind`: ``"json_decode_error"`` |
      ``"validation_error"`` | ``"unknown_error"``.
    - `raw_length`: byte length of the original response.
    - `raw_sha256_prefix`: first 16 hex chars of the sha256 digest —
      enough to cluster recurring failures in logs without carrying
      the body.
    - `first_non_ws_char` / `last_non_ws_char`: single characters that
      signal common malformations (``{`` vs ``\\``` vs prose letter).
    - `looks_like_markdown_fence`: the stripped response opens with
      ``` ``` ``` ```. Distinguishes fence-wrap from real parse errors.
    - `starts_with_json_object`: the stripped response opens with
      ``{``. A ``false`` here with a JSON-decode error almost always
      means prose preamble.
    - `validation_locs`: on Pydantic validation errors, a compact list
      of ``{"loc": "a.b.c", "type": "extra_forbidden"}`` dicts with no
      input values. This captures schema-drift shape without leaking
      what the model invented.
    - `json_decode_message`: on JSON-decode errors, the short message
      from the exception (position, token). Safe to log because it
      only describes the failure syntax, not the surrounding bytes.
    """
    raw_bytes = raw.encode("utf-8", errors="replace")
    digest_prefix = hashlib.sha256(raw_bytes).hexdigest()[:16]
    stripped = raw.strip()

    summary: dict[str, Any] = {
        "raw_length": len(raw_bytes),
        "raw_sha256_prefix": digest_prefix,
        "first_non_ws_char": stripped[0] if stripped else None,
        "last_non_ws_char": stripped[-1] if stripped else None,
        "looks_like_markdown_fence": stripped.startswith(_JSON_FENCE_BARE_PREFIX),
        "starts_with_json_object": stripped.startswith("{"),
    }

    if isinstance(exc, ValidationError):
        summary["parse_error_kind"] = "validation_error"
        summary["validation_locs"] = [
            {
                "loc": ".".join(str(part) for part in error.get("loc", ())),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
    elif isinstance(exc, json.JSONDecodeError):
        summary["parse_error_kind"] = "json_decode_error"
        summary["json_decode_message"] = exc.msg
    else:
        summary["parse_error_kind"] = "unknown_error"

    return summary


RejectionCode = Literal[
    "version_mismatch",
    "duplicate_question",
    "off_topic_question",
    "architecture_commit_premature_unresolved_choices",
    "architecture_commit_illegal_tuple",
    "architecture_commit_unresolvable_capability",
    "architecture_commit_unresolvable_pattern",
    "architecture_commit_drift_from_pinned",
    "propose_plan_without_architecture_commit",
    "propose_plan_missing_draft_plan",
    "propose_plan_draft_plan_structural_mismatch",
    "repair_attempted_commit_drift",
]


class RejectionReason(_OrchestratorModel):
    """Structured rejection the planner retry loop consumes.

    `code` is machine-readable so the retry loop can branch without
    parsing prose. `detail` is a short human-grade explanation for logs
    and telemetry. `current_version` is populated on `version_mismatch`
    so the planner can retry with the fresh stamp.
    """

    code: RejectionCode
    detail: str
    current_version: Optional[int] = None


@dataclass(frozen=True)
class OrchestrationContext:
    """Per-turn context the guardrails evaluate against.

    Context is computed once per turn by the caller and handed to
    `evaluate_planner_output`; the orchestrator itself is stateless.

    - `current_version` is the session's live `planning_state_version`.
    - `session_state` is the currently-persisted PlanningState. The
      `architecture_commit` field gates `propose_plan` acceptance.
    - `asked_question_ids` is the set of canonical question IDs the
      planner has already asked this session; combined with
      `has_new_evidence` to reject infinite-loop interrogation.
    - `unresolved_architectural_choices` names the architecture choices
      still open (e.g. `terminal_output`, `primary_runtime_input`).
    - `required_slot_names` is the union of slot names required by the
      current pattern candidates. A question resolving neither an
      unresolved choice nor a required slot is off-topic.
    """

    current_version: int
    session_state: PlanningState
    asked_question_ids: frozenset[str] = field(default_factory=frozenset[str])
    has_new_evidence: bool = False
    unresolved_architectural_choices: frozenset[str] = field(
        default_factory=frozenset[str]
    )
    required_slot_names: frozenset[str] = field(default_factory=frozenset[str])


def evaluate_planner_output(
    output: PlannerOutput,
    context: OrchestrationContext,
) -> RejectionReason | None:
    """Run monotonicity guardrails on a planner turn.

    Returns ``None`` on acceptance. On rejection, returns a structured
    `RejectionReason` with a machine-readable code the planner retry
    loop can consume. Guardrails fire in a deliberate order — the
    version check runs first because a stale delta invalidates any
    downstream signal it carries.
    """
    version_violation = _check_version(output, context)
    if version_violation is not None:
        return version_violation

    preservation_violation = _check_commit_preservation(output, context)
    if preservation_violation is not None:
        return preservation_violation

    action = output.planner_action

    if isinstance(action, AskQuestionAction):
        return _check_ask_question(action, context)
    if isinstance(action, CommitArchitectureAction):
        return _check_commit_architecture(output, context)
    if isinstance(action, ProposePlanAction):
        return _check_propose_plan(output, context)
    return None


def _check_commit_preservation(
    output: PlannerOutput, context: OrchestrationContext
) -> RejectionReason | None:
    """Reject any turn that would drift an already-pinned architecture commit.

    Once a commit is pinned on the session state, it is the canonical
    contract between the planner's discovery phase and downstream
    persistence. A follow-up turn may carry the pinned commit verbatim
    in `planning_state_delta.architecture_commit` (identity preservation)
    or omit it entirely (preservation by absence). A divergent body —
    different hash, different tuples_chain, different chosen_patterns —
    is drift, not progress: the repair helper rejects it post-hoc, but
    by then the accepted turn has already been dispatched.
    """
    pinned = context.session_state.architecture_commit
    if pinned is None:
        return None
    delta_commit = output.planning_state_delta.architecture_commit
    if delta_commit is None:
        return None
    try:
        assert_architecture_commit_unchanged(before=pinned, after=delta_commit)
    except CommitDriftError as exc:
        return RejectionReason(
            code="architecture_commit_drift_from_pinned",
            detail=str(exc),
        )
    return None


def _check_version(
    output: PlannerOutput, context: OrchestrationContext
) -> RejectionReason | None:
    delta_version = output.planning_state_delta.base_planning_state_version
    if delta_version != context.current_version:
        return RejectionReason(
            code="version_mismatch",
            detail=(
                f"planner sent base_planning_state_version={delta_version}, "
                f"session is at {context.current_version}"
            ),
            current_version=context.current_version,
        )
    return None


def _check_ask_question(
    action: AskQuestionAction, context: OrchestrationContext
) -> RejectionReason | None:
    question_id = action.payload.question_id
    slot_name = action.payload.slot_name

    resolves_something = (
        question_id in context.unresolved_architectural_choices
        or slot_name in context.unresolved_architectural_choices
        or slot_name in context.required_slot_names
    )
    if not resolves_something:
        return RejectionReason(
            code="off_topic_question",
            detail=(
                f"question_id={question_id!r} / slot_name={slot_name!r} "
                "resolves no unresolved_architectural_choice and no required slot"
            ),
        )

    if question_id in context.asked_question_ids and not context.has_new_evidence:
        return RejectionReason(
            code="duplicate_question",
            detail=(
                f"question_id={question_id!r} already asked this session and no "
                "new evidence arrived since"
            ),
        )
    return None


def _check_commit_architecture(
    output: PlannerOutput, context: OrchestrationContext
) -> RejectionReason | None:
    if context.session_state.architecture_commit is not None:
        return RejectionReason(
            code="architecture_commit_drift_from_pinned",
            detail=(
                "architecture was already pinned on this session; a second "
                "commit_architecture would overwrite the canonical contract. "
                "Emit confirm_requirements or propose_plan to advance the "
                "turn, or start a new session if the commitment is stale"
            ),
        )

    if context.unresolved_architectural_choices:
        return RejectionReason(
            code="architecture_commit_premature_unresolved_choices",
            detail=(
                "cannot commit architecture while unresolved_architectural_choices "
                f"is non-empty: {sorted(context.unresolved_architectural_choices)}"
            ),
        )

    commit = output.planning_state_delta.architecture_commit
    if commit is None:
        return RejectionReason(
            code="architecture_commit_illegal_tuple",
            detail="commit_architecture action requires a populated architecture_commit delta",
        )

    for triple in commit.tuples_chain:
        if not _tuple_is_legal(
            triple.input_type, triple.output_type, triple.output_mode
        ):
            return RejectionReason(
                code="architecture_commit_illegal_tuple",
                detail=(
                    "illegal step-io tuple per FCM: "
                    f"input_type={triple.input_type!r}, "
                    f"output_type={triple.output_type!r}, "
                    f"output_mode={triple.output_mode!r}"
                ),
            )

    for capability in commit.required_capabilities:
        if capability not in CAPABILITY_REGISTRY:
            return RejectionReason(
                code="architecture_commit_unresolvable_capability",
                detail=(
                    f"required capability {capability!r} is not in FCM "
                    "CAPABILITY_REGISTRY"
                ),
            )

    if not commit.chosen_patterns:
        return RejectionReason(
            code="architecture_commit_unresolvable_pattern",
            detail=(
                "commit_architecture must declare at least one chosen_pattern; "
                "otherwise pattern-specific architectural slots cannot be "
                "checked and a later pattern-narrowing turn becomes ambiguous"
            ),
        )

    for pattern_id in commit.chosen_patterns:
        if pattern_id not in PATTERN_REGISTRY:
            return RejectionReason(
                code="architecture_commit_unresolvable_pattern",
                detail=(f"chosen pattern {pattern_id!r} is not in PATTERN_REGISTRY"),
            )
        pattern = PATTERN_REGISTRY[pattern_id]
        if pattern.polarity != "positive":
            return RejectionReason(
                code="architecture_commit_unresolvable_pattern",
                detail=(
                    f"chosen pattern {pattern_id!r} has polarity "
                    f"{pattern.polarity!r}; only positive patterns are "
                    "committable. Negative patterns are anti-patterns the "
                    "knowledge pack teaches the planner to avoid, not commit"
                ),
            )

    resolved_slot_names = frozenset(context.session_state.resolved_slots.keys())
    pattern_required_slots = frozenset(
        slot_name
        for pattern_id in commit.chosen_patterns
        for slot_name in PATTERN_REGISTRY[pattern_id].required_architectural_slots
    )
    unresolved_pattern_slots = pattern_required_slots - resolved_slot_names
    if unresolved_pattern_slots:
        return RejectionReason(
            code="architecture_commit_premature_unresolved_choices",
            detail=(
                "cannot commit architecture while chosen_patterns require "
                f"slots {sorted(unresolved_pattern_slots)} that are not yet "
                "resolved in PlanningState.resolved_slots"
            ),
        )
    return None


def _check_propose_plan(
    output: PlannerOutput, context: OrchestrationContext
) -> RejectionReason | None:
    commit = context.session_state.architecture_commit
    if commit is None:
        return RejectionReason(
            code="propose_plan_without_architecture_commit",
            detail=(
                "propose_plan is only allowed once PlanningState.architecture_commit "
                "is populated via a prior commit_architecture turn"
            ),
        )

    draft_plan = output.planning_state_delta.draft_plan
    if draft_plan is None:
        return RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail=(
                "propose_plan must re-emit the draft_plan in "
                "planning_state_delta so structural parity against the "
                "committed architecture can run every turn; a bare "
                "plan_reference cannot be trusted because persisted plans "
                "carry no architecture binding"
            ),
        )

    draft_step_count = len(draft_plan.steps)
    commit_step_count = len(commit.tuples_chain)
    if draft_step_count != commit_step_count:
        return RejectionReason(
            code="propose_plan_draft_plan_structural_mismatch",
            detail=(
                f"draft_plan has {draft_step_count} step(s) but "
                f"architecture_commit.tuples_chain has {commit_step_count}; "
                "proposed plan must honor the committed tuple-chain length"
            ),
        )
    return None


def _tuple_is_legal(input_type: str, output_type: str, output_mode: str) -> bool:
    """Coerce the orchestrator's string literals to FCM enums and defer
    to `flow_capability_manifest.supports_step_io_tuple` as the single
    engine-truth for tuple legality.

    `any` is not a legal FlowInputType at step-io level — it maps to
    `None` so TEMPLATE_FILL / TRANSCRIBE_ONLY checks run without a
    concrete input-type claim.
    """
    coerced_input: FlowInputType | None
    if input_type == "any":
        coerced_input = None
    else:
        try:
            coerced_input = FlowInputType(input_type)
        except ValueError:
            return False

    try:
        coerced_output = FlowOutputType(output_type)
        coerced_mode = FlowOutputMode(output_mode)
    except ValueError:
        return False

    return supports_step_io_tuple(
        input_type=coerced_input,
        output_type=coerced_output,
        output_mode=coerced_mode,
    )


__all__ = [
    "AskQuestionAction",
    "AskQuestionPayload",
    "CommitArchitectureAction",
    "CommitArchitecturePayload",
    "ConfirmRequirementsAction",
    "ConfirmRequirementsPayload",
    "DraftPlanEnvelope",
    "OrchestrationContext",
    "PlannerAction",
    "PlannerOutput",
    "PlanningStateDelta",
    "ProposePlanAction",
    "ProposePlanPayload",
    "RejectionCode",
    "RejectionReason",
    "evaluate_planner_output",
    "parse_planner_output",
    "summarize_parse_failure",
]
