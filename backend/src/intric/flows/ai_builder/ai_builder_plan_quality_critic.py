from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from intric.flows.ai_builder.ai_builder_critic_invariants import (
    CriticContext,
    render_critic_issues,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    resolve_output_intent,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    mixed_audio_document_input_requested,
)
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    FlowDraftSpecCore,
)
from intric.flows.ai_builder.ai_builder_plan_store import format_revision_feedback
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.domain.flow import Flow


def build_conversation_aware_quality_feedback(
    conversation: list[ConversationMessage] | list[Mapping[str, Any]],
    spec: FlowDraftSpecCore,
    *,
    flow: Flow | None = None,
    aggregation_intent: AggregationIntent = "linear",
) -> str | None:
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
        requirements_state.latest_summary.model_dump(mode="json")
        if requirements_state.latest_summary is not None
        else None
    )
    signal_text = "\n".join(part for part in (text, requirements_text) if part)
    planner_patterns = detect_planner_pattern_signals(signal_text)
    output_intent = resolve_output_intent(text, answer_signals)

    context = CriticContext(
        spec=spec,
        flow=flow,
        answer_signals=answer_signals,
        text=text,
        requirements_text=requirements_text,
        signal_text=signal_text,
        planner_patterns=planner_patterns,
        output_intent=output_intent,
        mixed_audio_doc_input=mixed_audio_document_input_requested(text, flow=flow),
        aggregation_intent=aggregation_intent,
    )
    issues = render_critic_issues(context)

    if not issues:
        return None
    return format_revision_feedback("Quality issues", issues)
