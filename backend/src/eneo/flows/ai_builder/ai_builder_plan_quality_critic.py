from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CriticContext,
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_feedback_formatting import (
    format_revision_feedback,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    extract_requested_output_sections,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
    form_intake_signal_values_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_resource_catalog import (
        AIBuilderResourceCatalog,
    )


def build_conversation_aware_quality_feedback(
    conversation: list[ConversationMessage] | list[Mapping[str, Any]],
    spec: FlowDraftSpecCore,
    *,
    flow: Flow | None = None,
    aggregation_intent: AggregationIntent = "linear",
    resource_catalog: "AIBuilderResourceCatalog | None" = None,
    planning_state: PlanningState | None = None,
) -> str | None:
    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=flow,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
    )
    return build_quality_feedback_from_critic_context(
        context,
        include_architecture=True,
    )


def build_conversation_critic_context(
    conversation: list[ConversationMessage] | list[Mapping[str, Any]],
    spec: FlowDraftSpecCore,
    *,
    flow: Flow | None = None,
    aggregation_intent: AggregationIntent = "linear",
    resource_catalog: "AIBuilderResourceCatalog | None" = None,
    planning_state: PlanningState | None = None,
) -> CriticContext:
    answer_signals = extract_answer_signals(conversation)
    text = aggregate_freeform_user_text(conversation)
    requirements_state = resolve_requirements_state(
        [
            item
            if isinstance(item, ConversationMessage)
            else ConversationMessage.model_validate(item)
            for item in conversation
        ]
    )
    requirements_text = build_requirements_signal_text(
        requirements_state.latest_summary
    )
    signal_text = "\n".join(part for part in (text, requirements_text) if part)
    model_form_intake_signals = form_intake_signal_values_from_planning_state(
        planning_state
    )
    planner_patterns = detect_planner_pattern_signals(
        signal_text,
        model_form_intake_signals=model_form_intake_signals,
    )
    output_intent = resolve_output_intent(text, answer_signals)
    input_intent = resolve_input_intent(text, answer_signals, flow=flow)

    return CriticContext(
        spec=spec,
        flow=flow,
        answer_signals=answer_signals,
        text=text,
        requirements_text=requirements_text,
        signal_text=signal_text,
        planner_patterns=planner_patterns,
        output_intent=output_intent,
        mixed_audio_doc_input=input_intent.needs_architecture_clarification,
        primary_runtime_input=input_intent.primary_runtime_input,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
        requested_output_sections=extract_requested_output_sections(
            signal_text,
            model_form_intake_signals=model_form_intake_signals,
        ),
    )


def build_quality_feedback_from_critic_context(
    context: CriticContext,
    *,
    include_architecture: bool = False,
) -> str | None:
    issues = [
        issue.remediation
        for issue in evaluate_critic_invariants(context)
        if include_architecture or issue.kind == "semantic"
    ]
    if not issues:
        return None
    return format_revision_feedback("Quality issues", issues)
