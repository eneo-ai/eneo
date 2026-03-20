from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    ConversationMessage,
    FlowDraftSpecCore,
    LintWarning,
    PlannerPlanEnvelope,
)
from intric.flows.ai_builder.ai_builder_prompts import build_plan_summary
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationError


def build_lint_warnings(validation: Any) -> list[LintWarning]:
    return [
        LintWarning(
            step_ref=warning.step_ref,
            code=warning.code,
            message=warning.message,
            severity=warning.severity,
        )
        for warning in validation.warnings
    ]


def build_plan_envelope(
    *,
    spec: FlowDraftSpecCore,
    assumptions: list[str],
    plan_rationale: str | None,
    reasoning: str | None,
    validation: Any,
) -> PlannerPlanEnvelope:
    return PlannerPlanEnvelope(
        spec=spec,
        assumptions=assumptions,
        plan_rationale=plan_rationale,
        reasoning=reasoning,
        lint_warnings=build_lint_warnings(validation),
    )


def warnings_for_quality_retry(
    validation: Any,
    *,
    retry_warning_codes: set[str],
) -> list[LintWarning]:
    return [
        warning
        for warning in validation.warnings
        if warning.code in retry_warning_codes
    ]


def format_revision_feedback(title: str, issues: list[str]) -> str:
    if not issues:
        return title
    numbered = "\n".join(f"{index}. {issue}" for index, issue in enumerate(issues, start=1))
    return f"{title}:\n{numbered}"


def format_validation_feedback(
    *,
    spec: FlowDraftSpecCore,
    errors: list[SpecValidationError],
) -> str:
    feedback = format_revision_feedback(
        "Validation errors",
        [error.message for error in errors],
    )

    if not any(_requires_reference_guidance(error) for error in errors):
        return feedback

    declared_refs = ", ".join(step.plan_step_ref for step in spec.steps if step.plan_step_ref)
    reference_guidance = [
        "Step reference rules:",
        "- Use the exact plan_step_ref values declared in steps[*].plan_step_ref inside all template bindings.",
        "- In propose_flow drafts, step_a / step_b style refs are authoring aliases. Do not switch to runtime aliases like step_1.",
    ]
    if declared_refs:
        reference_guidance.append(f"- Declared step refs in this draft: {declared_refs}")
    reference_guidance.append(
        "- If you rename a plan_step_ref, update every {{ ref.output.* }} binding that points to it."
    )
    return f"{feedback}\n\n" + "\n".join(reference_guidance)


def _requires_reference_guidance(error: SpecValidationError) -> bool:
    if error.code in {
        "invalid_step_reference",
        "future_step_reference",
        "structured_access_requires_json_output",
        "unknown_output_contract_field",
    }:
        return True

    if error.code != "flow_step_invalid":
        return False

    message = error.message.casefold()
    return any(
        marker in message
        for marker in (
            "invalid step reference",
            "input bindings may only reference outputs from earlier steps",
            "input binding references unknown step order",
        )
    )


async def store_plan_and_update_conversation(
    *,
    repo: AIBuilderRepository,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    assistant_content: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    spec: FlowDraftSpecCore,
    assumptions: list[str],
    plan_rationale: str | None,
    reasoning: str | None,
    validation: Any,
    edit_result_json: dict[str, Any] | None = None,
) -> tuple[BuilderPlan, PlannerPlanEnvelope]:
    envelope = build_plan_envelope(
        spec=spec,
        assumptions=assumptions,
        plan_rationale=plan_rationale,
        reasoning=reasoning,
        validation=validation,
    )
    plan = await persist_plan(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        spec=spec,
        envelope=envelope,
        edit_result_json=edit_result_json,
    )
    append_plan_messages(
        conversation=conversation,
        assistant_content=assistant_content,
        tool_call_id=tool_call_id,
        arguments=arguments,
        spec=spec,
        assumptions=assumptions,
    )
    await append_session_messages(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation=conversation,
        start_index=new_messages_start,
    )
    return plan, envelope


async def persist_plan(
    *,
    repo: AIBuilderRepository,
    tenant_id: UUID,
    session_id: UUID,
    spec: FlowDraftSpecCore,
    envelope: PlannerPlanEnvelope,
    edit_result_json: dict[str, Any] | None = None,
) -> BuilderPlan:
    await repo.supersede_existing_plans(
        session_id=session_id,
        tenant_id=tenant_id,
    )
    plan = await repo.create_plan(
        session_id=session_id,
        tenant_id=tenant_id,
        spec=spec,
        envelope=envelope,
        edit_result_json=edit_result_json,
    )
    await repo.update_session_latest_plan(
        session_id=session_id,
        tenant_id=tenant_id,
        plan_id=plan.id,
    )
    return plan


async def append_session_messages(
    *,
    repo: AIBuilderRepository,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    start_index: int,
) -> None:
    await repo.append_session_messages(
        session_id=session_id,
        tenant_id=tenant_id,
        conversation=conversation[start_index:],
    )


def append_plan_messages(
    *,
    conversation: list[ConversationMessage],
    assistant_content: str,
    tool_call_id: str,
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
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            tool_calls=[{
                "id": tool_call_id,
                "name": PROPOSE_FLOW_TOOL_NAME,
                "arguments": compact_arguments,
            }],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=build_plan_summary(spec, assumptions),
            tool_call_id=tool_call_id,
        )
    )
