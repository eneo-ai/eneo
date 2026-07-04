from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    assert_architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposal,
    LintSeverity,
    LintWarning,
)
from eneo.flows.ai_builder.ai_builder_prompts import build_plan_summary
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import CompiledProposal
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class StoredPlanResult:
    plan: BuilderPlan
    proposal: FlowBuilderProposal
    new_planning_state_version: int


def build_lint_warnings(validation: SpecValidationResult) -> list[LintWarning]:
    return [
        LintWarning(
            step_ref=warning.step_ref,
            code=warning.code,
            message=warning.message,
            severity=warning.severity,
        )
        for warning in validation.warnings
        if _is_user_visible_lint_warning(warning)
    ]


def _is_user_visible_lint_warning(warning: LintWarning) -> bool:
    """Return whether a lint warning is relevant in the end-user plan UI.

    Info-level quality lints are useful for internal plan quality feedback and
    self-correction, but they are usually not actionable for the user approving
    a plan. Keep the public plan surface focused on user-relevant warnings.
    """
    return warning.severity == LintSeverity.WARNING


def build_flow_builder_proposal(
    compiled: CompiledProposal,
) -> FlowBuilderProposal:
    if compiled.content.lint_warnings:
        raise ValueError(
            "Compiled proposal content must not set lint_warnings; they are "
            "derived from compiled.validation at the storage boundary."
        )
    content = compiled.content.model_copy(
        update={"lint_warnings": build_lint_warnings(compiled.validation)}
    )
    return FlowBuilderProposal(
        content=content,
        reasoning=compiled.reasoning,
        resource_bindings=compiled.resource_bindings,
    )


async def store_plan_and_update_conversation(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    assistant_content: str,
    assistant_metadata: dict[str, Any] | None = None,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    compiled: CompiledProposal,
    flow: "Flow | None" = None,
    planning_state_overlay: PlanningState | None = None,
) -> StoredPlanResult:
    proposal = build_flow_builder_proposal(compiled)
    append_plan_messages(
        conversation=conversation,
        assistant_content=assistant_content,
        assistant_metadata=assistant_metadata,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        spec=compiled.content.spec,
        assumptions=compiled.content.assumptions,
    )
    async with repo.savepoint():
        prior_state = await repo.load_planning_state(
            session_id=turn.session_id, tenant_id=turn.tenant_id
        )
        plan = await _persist_active_send_plan_proposal(
            repo=repo,
            turn=turn,
            proposal=proposal,
        )
        persisted = await append_session_messages(
            repo=repo,
            turn=turn,
            conversation=conversation,
            start_index=new_messages_start,
        )
        planning_state = build_planning_state_from_conversation(persisted, flow=flow)
        # Current-turn overlay must run before prior state: carry-forward only
        # fills missing planner-owned fields, so the current upload role wins.
        carry_forward_persisted_planner_state(
            planning_state,
            planning_state_overlay,
        )
        carry_forward_persisted_planner_state(planning_state, prior_state)
        prior_commit = prior_state.architecture_commit if prior_state else None
        assert_architecture_commit_draft_matches_pinned(
            before=prior_commit,
            after=derive_architecture_commit_draft(planning_state),
        )
        new_version = await repo.save_planning_state(
            session_id=turn.session_id,
            tenant_id=turn.tenant_id,
            state=planning_state,
            base_version=turn.base_planning_state_version,
        )
    return StoredPlanResult(
        plan=plan,
        proposal=proposal,
        new_planning_state_version=new_version,
    )


async def _persist_active_send_plan_proposal(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    proposal: FlowBuilderProposal,
) -> BuilderPlan:
    await repo.supersede_existing_plans(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
    )
    plan = await repo.create_plan(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
        proposal=proposal,
    )
    await repo.update_session_latest_plan(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
        plan_id=plan.id,
        lease=turn.lease,
    )
    return plan


async def append_session_messages(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    start_index: int,
) -> list[ConversationMessage]:
    return await repo.append_session_messages(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
        conversation=conversation[start_index:],
        lease=turn.lease,
    )


def append_plan_messages(
    *,
    conversation: list[ConversationMessage],
    assistant_content: str,
    assistant_metadata: dict[str, Any] | None = None,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    spec: FlowDraftSpecCore,
    assumptions: list[str],
) -> None:
    # Strip reasoning and full proposal from stored arguments to prevent
    # leaking internal chain-of-thought through the session conversation API.
    # Replace with compact summary — full spec lives in BuilderPlans table.
    compact_arguments = {
        "flow_name": spec.flow_name,
        "step_count": len(spec.steps),
        "step_names": [s.name for s in spec.steps],
        "plan_rationale": arguments.get("plan_rationale", ""),
    }
    tool_call = make_persisted_assistant_tool_call(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=compact_arguments,
    )
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            metadata=assistant_metadata,
            tool_calls=[tool_call.model_dump(mode="json")],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=build_plan_summary(spec, assumptions),
            tool_call_id=tool_call_id,
        )
    )
