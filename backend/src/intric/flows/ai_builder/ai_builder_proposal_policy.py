"""Pure proposal policy shared by create and edit proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    ui_language_from_metadata,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    resolve_output_intent,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    format_revision_feedback,
    warnings_for_quality_retry,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_plan_edit_context import (
        AIBuilderPlanEditContext,
    )
    from intric.flows.ai_builder.ai_builder_resource_catalog import (
        AIBuilderResourceCatalog,
    )
    from intric.flows.domain.flow import Flow

_PRESERVED_PLAN_EDIT_TERMINAL_TYPES = frozenset(
    {OutputType.JSON, OutputType.PDF, OutputType.DOCX}
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
        )
        latest_output_type = _output_type_from_intent(output_intent.terminal_output)
        return latest_output_type or _terminal_output_type_from_prior_plan(prior_plan)

    output_intent = resolve_output_intent(
        aggregate_freeform_user_text(conversation),
        extract_answer_signals(conversation),
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


def _output_type_from_intent(terminal_output: str | None) -> OutputType | None:
    if terminal_output is None:
        return None
    return {
        "pdf_document": OutputType.PDF,
        "docx_document": OutputType.DOCX,
        "structured_json": OutputType.JSON,
        "structured_text": OutputType.TEXT,
    }.get(terminal_output)
