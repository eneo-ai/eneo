"""Normalize LLM planner output into server-owned mechanics.

This is intentionally narrow. The LLM still chooses the high-level
planner action and user-facing prose, but deterministic cross-field
mechanics are repaired before guardrail evaluation when the server can
derive them from `OrchestrationContext`.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    CommitArchitecturePayload,
    OrchestrationContext,
    PlannerOutput,
)


def normalize_planner_output(
    output: PlannerOutput,
    context: OrchestrationContext,
) -> PlannerOutput:
    """Return a normalized planner output for evaluator consumption.

    `commit_architecture` is the main fragile cross-field action: the
    model can choose the action but omit or freehand the accompanying
    architecture draft. When the current server state has enough
    resolved slots, overwrite that draft with the deterministic
    server-derived one.
    """
    normalized = _pivot_disallowed_question_to_commit(output, context)

    if not isinstance(normalized.planner_action, CommitArchitectureAction):
        return normalized

    draft = derive_architecture_commit_draft(context.session_state)
    if draft is None:
        return normalized

    normalized = normalized.model_copy(deep=True)
    normalized.planning_state_delta.architecture_commit = draft
    return normalized


def _pivot_disallowed_question_to_commit(
    output: PlannerOutput,
    context: OrchestrationContext,
) -> PlannerOutput:
    """Deterministically recover when the model asks after asking is closed.

    Once the action policy says `ask_question` is not allowed, an LLM
    repair prompt cannot produce a valid question. If the same policy
    says the architecture can be committed, the server can safely pivot
    to `commit_architecture`; the semantic commit body is derived below
    from `PlanningState`.
    """
    policy = context.action_policy
    if policy is None:
        return output
    if not isinstance(output.planner_action, AskQuestionAction):
        return output
    if "ask_question" in policy.allowed_action_kinds:
        return output
    if "commit_architecture" not in policy.allowed_action_kinds:
        return output

    normalized = output.model_copy(deep=True)
    normalized.planner_action = CommitArchitectureAction(
        kind="commit_architecture",
        payload=CommitArchitecturePayload(
            note="Architecture committed from resolved planning state."
        ),
    )
    return normalized


__all__ = ["normalize_planner_output"]
