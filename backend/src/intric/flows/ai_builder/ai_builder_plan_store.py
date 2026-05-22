from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    LintSeverity,
    LintWarning,
    PlannerPlanEnvelope,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
)
from intric.flows.ai_builder.ai_builder_prompts import build_plan_summary
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from intric.flows.flow_resource_bindings import LocalResourceBinding

if TYPE_CHECKING:
    from intric.flows.flow import Flow


@dataclass(frozen=True, slots=True)
class StoredPlanResult:
    plan: BuilderPlan
    envelope: PlannerPlanEnvelope
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


def build_plan_envelope(
    *,
    spec: FlowDraftSpecCore,
    assumptions: list[str],
    plan_rationale: str | None,
    reasoning: str | None,
    validation: SpecValidationResult,
) -> PlannerPlanEnvelope:
    return PlannerPlanEnvelope(
        spec=spec,
        assumptions=assumptions,
        plan_rationale=plan_rationale,
        reasoning=reasoning,
        lint_warnings=build_lint_warnings(validation),
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
    spec: FlowDraftSpecCore,
    assumptions: list[str],
    plan_rationale: str | None,
    reasoning: str | None,
    validation: SpecValidationResult,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
    edit_result: BuilderPlanEditResult | None = None,
    flow: "Flow | None" = None,
) -> StoredPlanResult:
    envelope = build_plan_envelope(
        spec=spec,
        assumptions=assumptions,
        plan_rationale=plan_rationale,
        reasoning=reasoning,
        validation=validation,
    )
    append_plan_messages(
        conversation=conversation,
        assistant_content=assistant_content,
        assistant_metadata=assistant_metadata,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        spec=spec,
        assumptions=assumptions,
    )
    async with repo.savepoint():
        prior_state = await repo.load_planning_state(
            session_id=turn.session_id, tenant_id=turn.tenant_id
        )
        plan = await _persist_active_send_plan_proposal(
            repo=repo,
            turn=turn,
            spec=spec,
            envelope=envelope,
            resource_bindings=resource_bindings,
            edit_result=edit_result,
        )
        persisted = await append_session_messages(
            repo=repo,
            turn=turn,
            conversation=conversation,
            start_index=new_messages_start,
        )
        planning_state = build_planning_state_from_conversation(persisted, flow=flow)
        planning_state.draft_plan_id = plan.id
        planning_state.phase = "plan_proposed"
        carry_forward_persisted_planner_state(planning_state, prior_state)
        new_version = await repo.save_planning_state(
            session_id=turn.session_id,
            tenant_id=turn.tenant_id,
            state=planning_state,
            base_version=turn.base_planning_state_version,
        )
    return StoredPlanResult(
        plan=plan,
        envelope=envelope,
        new_planning_state_version=new_version,
    )


async def _persist_active_send_plan_proposal(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    spec: FlowDraftSpecCore,
    envelope: PlannerPlanEnvelope,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
    edit_result: BuilderPlanEditResult | None = None,
) -> BuilderPlan:
    await repo.supersede_existing_plans(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
    )
    plan = await repo.create_plan(
        session_id=turn.session_id,
        tenant_id=turn.tenant_id,
        spec=spec,
        envelope=envelope,
        resource_bindings=resource_bindings,
        edit_result=edit_result,
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
