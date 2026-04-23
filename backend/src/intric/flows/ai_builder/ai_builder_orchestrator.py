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
the turn is accepted. Action dispatch + atomic persistence land in later
slices and import from here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

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
    """
    payload = json.loads(raw) if isinstance(raw, str) else raw
    return PlannerOutput.model_validate(payload)


RejectionCode = Literal[
    "version_mismatch",
    "duplicate_question",
    "off_topic_question",
    "architecture_commit_premature_unresolved_choices",
    "architecture_commit_illegal_tuple",
    "architecture_commit_unresolvable_capability",
    "propose_plan_without_architecture_commit",
    "propose_plan_draft_plan_structural_mismatch",
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

    action = output.planner_action

    if isinstance(action, AskQuestionAction):
        return _check_ask_question(action, context)
    if isinstance(action, CommitArchitectureAction):
        return _check_commit_architecture(output, context)
    if isinstance(action, ProposePlanAction):
        return _check_propose_plan(output, context)
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
    if draft_plan is not None:
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
]
