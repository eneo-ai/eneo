"""Route validated planner output to atomic persistence.

Once `evaluate_planner_output` accepts a `PlannerOutput`, exactly one
of three action paths runs:

- `commit_architecture` — finalize the delta's semantic architecture
  draft into a persisted `ArchitectureCommit` and hand it to
  `AIBuilderRepository.commit_turn(architecture_commit=...)`, the only
  path that stamps a commit on `PlanningState`.
- `ask_question` / `confirm_requirements` — persist the conversation
  and planner-owned delta through the same `commit_turn` call, but with
  ``architecture_commit=None`` so the repo's carry-forward helper keeps
  any prior commit intact.
Each persisted branch makes at most one `commit_turn` call and returns
a `PlannerDispatchResult` the caller uses to emit SSE events. A
`commit_architecture` action whose delta lacks an `architecture_commit`
raises `ValueError`; it is not swallowed. Errors propagated by
`commit_turn` itself pass through unchanged.

The planner's self-reported `signals_added` / `slots_resolved` on the
delta are intentionally *not* applied by the dispatcher: `commit_turn`
rebuilds `PlanningState` from the persisted conversation, so those
fields are claims for guardrails to verify, never the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    ConfirmRequirementsAction,
    PlannerOutput,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.planning_state import ArchitectureCommit

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from intric.flows.flow import Flow


PlannerActionKind = Literal[
    "ask_question",
    "commit_architecture",
    "confirm_requirements",
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
    turn: SessionSendTurn,
    output: PlannerOutput,
    new_messages: list[ConversationMessage],
    flow: "Flow | None" = None,
) -> PlannerDispatchResult:
    """Atomically persist the planner's turn.

    Preconditions: `evaluate_planner_output(output, ...)` must have
    returned ``None`` for this `output`. The dispatcher does not
    re-run guardrails; it trusts the caller to have done so.

    The `commit_architecture` branch is the only one that reads from
    `output.planning_state_delta.architecture_commit`. The planner
    provides a semantic draft only; this dispatcher adds server-owned
    `architecture_hash` and `committed_at` before persistence. The
    other planner-owned branches rely on `commit_turn`'s rebuild-from-
    conversation path to carry forward the prior `PlanningState`.

    Plan proposal is intentionally not supported here; the server routes
    that phase through the task-specific proposal processor instead of
    the planner union.
    """
    action = output.planner_action
    architecture_commit: ArchitectureCommit | None

    match action:
        case CommitArchitectureAction():
            architecture_commit_draft = output.planning_state_delta.architecture_commit
            if architecture_commit_draft is None:
                raise ValueError(
                    "commit_architecture action reached the dispatcher with "
                    "planning_state_delta.architecture_commit=None; the caller "
                    "must pass the output through evaluate_planner_output first, "
                    "which rejects this shape as architecture_commit_missing_delta."
                )
            architecture_commit = finalize_architecture_commit(
                architecture_commit_draft
            )
        case AskQuestionAction() | ConfirmRequirementsAction():
            architecture_commit = None
        case _ as unhandled:
            assert_never(unhandled)

    new_version = await repo.commit_turn(
        turn=turn,
        new_messages=new_messages,
        flow=flow,
        architecture_commit=architecture_commit,
    )

    return PlannerDispatchResult(
        action_kind=action.kind,
        new_planning_state_version=new_version,
    )
