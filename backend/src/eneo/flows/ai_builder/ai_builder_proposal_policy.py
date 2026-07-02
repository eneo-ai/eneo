"""Pure proposal policy shared by create and edit proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    slot_classification_from_metadata,
    ui_language_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_create_feedback import (
    format_create_critic_feedback,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    enforce_architecture_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    LintWarning,
)
from eneo.flows.ai_builder.ai_builder_draft_preflight import run_draft_preflight
from eneo.flows.ai_builder.ai_builder_feedback_formatting import (
    format_revision_feedback,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
    build_conversation_critic_context,
)
from eneo.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationError,
    SpecValidationResult,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
        AIBuilderPlanEditContext,
    )
    from eneo.flows.ai_builder.ai_builder_resource_catalog import (
        AIBuilderResourceCatalog,
    )
    from eneo.flows.domain.flow import Flow

_PRESERVED_PLAN_EDIT_TERMINAL_TYPES = frozenset(
    {OutputType.JSON, OutputType.PDF, OutputType.DOCX}
)


def warnings_for_quality_retry(
    validation: SpecValidationResult,
    *,
    retry_warning_codes: set[str] | frozenset[str],
) -> list[LintWarning]:
    return [
        warning
        for warning in validation.warnings
        if warning.code in retry_warning_codes
    ]


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

    declared_refs = ", ".join(
        step.plan_step_ref for step in spec.steps if step.plan_step_ref
    )
    reference_guidance = [
        "Step reference rules:",
        "- Use the exact plan_step_ref values declared in steps[*].plan_step_ref inside all template bindings.",
        "- In AI Builder drafts, step_a / step_b style refs are authoring aliases. Do not switch to runtime aliases like step_1.",
    ]
    if declared_refs:
        reference_guidance.append(
            f"- Declared step refs in this draft: {declared_refs}"
        )
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
            "input bindings may only reference outputs from earlier steps",
            "input binding references unknown step order",
        )
    )


def format_quality_feedback(
    validation: SpecValidationResult,
    *,
    quality_retry_warning_codes: set[str] | frozenset[str],
) -> str | None:
    quality_warnings = warnings_for_quality_retry(
        validation,
        retry_warning_codes=quality_retry_warning_codes,
    )
    if not quality_warnings:
        return None
    return format_revision_feedback(
        "Quality issues",
        [warning.message for warning in quality_warnings],
    )


def format_contextual_quality_feedback(
    conversation: list[ConversationMessage],
    spec: FlowDraftSpecCore,
    *,
    flow: "Flow | None" = None,
    aggregation_intent: AggregationIntent = "linear",
    resource_catalog: "AIBuilderResourceCatalog | None" = None,
) -> str | None:
    return build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=flow,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
    )


def format_create_contextual_quality_feedback(
    *,
    conversation: list[ConversationMessage],
    spec: FlowDraftSpecCore,
    aggregation_intent: AggregationIntent,
    resource_catalog: "AIBuilderResourceCatalog | None",
) -> str | None:
    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=None,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
    )
    preflight = run_draft_preflight(context)
    enforce_architecture_critic_invariants(context, issues=preflight.issues)
    return format_create_critic_feedback(preflight.semantic_issues)


def resolve_ui_language(
    conversation: list[ConversationMessage],
) -> Literal["sv", "en"] | None:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        ui_language = ui_language_from_metadata(message.metadata)
        if ui_language in {"sv", "en"}:
            return ui_language
    return None


def terminal_output_type_for_conversation(
    conversation: list[ConversationMessage],
    *,
    plan_edit_context: "AIBuilderPlanEditContext | None",
    prior_plan: BuilderPlan | None,
) -> OutputType | None:
    if plan_edit_context is not None:
        user_messages = [
            message
            for message in conversation
            if message.role == "user" and message.content
        ]
        if not user_messages:
            return _terminal_output_type_from_prior_plan(prior_plan)
        latest_user_message = user_messages[-1]
        latest_user_content = latest_user_message.content
        if latest_user_content is None:
            return _terminal_output_type_from_prior_plan(prior_plan)
        output_intent = resolve_output_intent(
            latest_user_content,
            extract_answer_signals([latest_user_message]),
            conversation=[latest_user_message],
        )
        latest_output_type = _output_type_from_intent(output_intent.terminal_output)
        return (
            latest_output_type
            or _terminal_output_type_from_slot_classification(latest_user_message)
            or _terminal_output_type_from_prior_plan(prior_plan)
        )

    output_intent = resolve_output_intent(
        aggregate_freeform_user_text(conversation),
        extract_answer_signals(conversation),
        conversation=conversation,
    )
    return _output_type_from_intent(output_intent.terminal_output)


def _terminal_output_type_from_prior_plan(
    prior_plan: BuilderPlan | None,
) -> OutputType | None:
    if prior_plan is None or not prior_plan.spec.steps:
        return None
    output_type = prior_plan.spec.steps[-1].output_type
    if output_type in _PRESERVED_PLAN_EDIT_TERMINAL_TYPES:
        return output_type
    return None


def _terminal_output_type_from_slot_classification(
    message: ConversationMessage,
) -> OutputType | None:
    classification = slot_classification_from_metadata(message.metadata)
    if classification is None:
        return None
    for slot in classification.slots:
        if slot.slot_name == "terminal_output":
            return _output_type_from_intent(slot.value)
    return None


def _output_type_from_intent(terminal_output: str | None) -> OutputType | None:
    if terminal_output is None:
        return None
    return {
        "pdf_document": OutputType.PDF,
        "docx_document": OutputType.DOCX,
        "structured_json": OutputType.JSON,
        "structured_text": OutputType.TEXT,
    }.get(terminal_output)
