"""Route validated planner output to atomic persistence.

Once `evaluate_planner_output` accepts a `PlannerOutput`, exactly one
of four action paths runs:

- `commit_architecture` — extract the delta's `ArchitectureCommit` and
  hand it to `AIBuilderRepository.commit_turn(architecture_commit=...)`,
  the only path that stamps a commit on `PlanningState`.
- `ask_question` / `confirm_requirements` — persist the conversation
  and planner-owned delta through the same `commit_turn` call, but with
  ``architecture_commit=None`` so the repo's carry-forward helper keeps
  any prior commit intact.
- `propose_plan` — requires an adapter onto the legacy proposal
  processor that translates the orchestrator's `DraftPlanEnvelope`
  into the processor's tool-call shape. That adapter is not wired
  here; this branch raises `NotImplementedError` rather than silently
  dropping the draft plan.

Each persisted branch makes at most one `commit_turn` call and returns
a `PlannerDispatchResult` the caller uses to emit SSE events. The
`propose_plan` branch raises `NotImplementedError`, and a
`commit_architecture` action whose delta lacks an `architecture_commit`
raises `ValueError`; neither is swallowed. Errors propagated by
`commit_turn` itself pass through unchanged.

The planner's self-reported `signals_added` / `slots_resolved` on the
delta are intentionally *not* applied by the dispatcher: `commit_turn`
rebuilds `PlanningState` from the persisted conversation, so those
fields are claims for guardrails to verify, never the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never
from uuid import UUID

from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    ConfirmRequirementsAction,
    PlannerOutput,
    ProposePlanAction,
)
from intric.flows.ai_builder.planning_state import ArchitectureCommit

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from intric.flows.flow import Flow


PlannerActionKind = Literal[
    "ask_question",
    "commit_architecture",
    "confirm_requirements",
    "propose_plan",
]


@dataclass(frozen=True, slots=True)
class PlannerDispatchResult:
    """Outcome of routing one validated `PlannerOutput` to the repo.

    `action_kind` mirrors the input action's `kind` so callers
    pattern-match on a single discriminator to emit the right SSE
    event. `new_planning_state_version` is the monotonically-bumped
    value returned by `commit_turn`; clients attach it to events so
    stale local state can be discarded.
    """

    action_kind: PlannerActionKind
    new_planning_state_version: int


async def dispatch_planner_action(
    *,
    repo: "AIBuilderRepository",
    session_id: UUID,
    tenant_id: UUID,
    output: PlannerOutput,
    new_messages: list[ConversationMessage],
    flow: "Flow | None" = None,
    request_id: UUID | None = None,
    lock_token: UUID | None = None,
) -> PlannerDispatchResult:
    """Atomically persist the planner's turn.

    Preconditions: `evaluate_planner_output(output, ...)` must have
    returned ``None`` for this `output`. The dispatcher does not
    re-run guardrails; it trusts the caller to have done so.

    The `commit_architecture` branch is the only one that reads from
    `output.planning_state_delta.architecture_commit`. The other
    planner-owned branches rely on `commit_turn`'s rebuild-from-
    conversation path to carry forward the prior `PlanningState`.

    `propose_plan` is intentionally not supported here; its handoff
    shape is tied to the legacy proposal processor's tool-call path,
    and the translating adapter is not wired in this module.
    """
    action = output.planner_action
    architecture_commit: ArchitectureCommit | None

    match action:
        case ProposePlanAction():
            raise NotImplementedError(
                "propose_plan dispatch requires a proposal processor "
                "adapter that translates DraftPlanEnvelope into the "
                "processor's tool-call shape; that adapter is not wired "
                "in this module."
            )
        case CommitArchitectureAction():
            architecture_commit = output.planning_state_delta.architecture_commit
            if architecture_commit is None:
                raise ValueError(
                    "commit_architecture action reached the dispatcher with "
                    "planning_state_delta.architecture_commit=None; the caller "
                    "must pass the output through evaluate_planner_output first, "
                    "which rejects this shape as architecture_commit_illegal_tuple."
                )
        case AskQuestionAction() | ConfirmRequirementsAction():
            architecture_commit = None
        case _ as unhandled:
            assert_never(unhandled)

    new_version = await repo.commit_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        new_messages=new_messages,
        flow=flow,
        request_id=request_id,
        lock_token=lock_token,
        architecture_commit=architecture_commit,
    )

    return PlannerDispatchResult(
        action_kind=action.kind,
        new_planning_state_version=new_version,
    )
