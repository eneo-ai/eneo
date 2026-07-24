from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from eneo.flows.ai_builder.ai_builder_flow_context import build_plan_summary
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import CompiledProposal
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from eneo.flows.ai_builder.planning_state import PlanningState
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
        plan = await _persist_active_send_plan_proposal(
            repo=repo,
            turn=turn,
            proposal=proposal,
        )
        new_version = await repo.commit_turn(
            turn=turn,
            new_messages=conversation[new_messages_start:],
            flow=flow,
            planning_state_overlay=planning_state_overlay,
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
    # Store only the canonical proposal envelope, never raw model arguments that
    # could leak internal chain-of-thought through the session conversation API.
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
