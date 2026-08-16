from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_feedback import (
    format_revision_feedback,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CriticContext,
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    aggregate_unprompted_user_text,
    extract_answer_signals,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
    form_intake_signal_values_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_result_contract import derive_result_contract
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
    include_edit_topology_advisories: bool = True,
    compile_context: CreateCompileContext | None = None,
) -> str | None:
    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=flow,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
        compile_context=compile_context,
    )
    return build_quality_feedback_from_critic_context(
        context,
        include_architecture=True,
        include_edit_topology_advisories=include_edit_topology_advisories,
    )


def _output_intent_with_committed_state(
    text_derived: OutputIntentResolution,
    planning_state: PlanningState | None,
) -> OutputIntentResolution:
    """Committed planning state owns output intent; raw text is fallback.

    The keyword heuristic is negation-blind: a prompt that names DOCX only
    to reject it ("ingen DOCX-mall") resolved docx_document +
    template_fill_docx, and the critic killed correct plans against that
    misreading while the classifier had already committed the terminal
    correctly (2026-08-07, deterministic on the declared-terminal family).

    When a commit-grade terminal exists it wins, and the dependent
    DOCX/PDF mode comes from committed slots or stays None — an invariant
    that cannot establish the mode does not fire, which fails open instead
    of false-killing. With nothing committed, the text heuristic remains
    the only signal.
    """

    if planning_state is None:
        return text_derived
    terminal = planning_state.commit_grade_slot_value("terminal_output")
    if terminal is None:
        return text_derived
    return OutputIntentResolution(
        terminal_output=terminal,
        content_shape=text_derived.content_shape,
        docx_output_mode=(
            planning_state.commit_grade_slot_value("docx_output_mode")
            if terminal == "docx_document"
            else None
        ),
        pdf_generation_mode=(
            planning_state.commit_grade_slot_value("pdf_generation_mode")
            if terminal == "pdf_document"
            else None
        ),
    )


def build_conversation_critic_context(
    conversation: list[ConversationMessage] | list[Mapping[str, Any]],
    spec: FlowDraftSpecCore,
    *,
    flow: Flow | None = None,
    aggregation_intent: AggregationIntent | None = None,
    resource_catalog: "AIBuilderResourceCatalog | None" = None,
    planning_state: PlanningState | None = None,
    compile_context: CreateCompileContext | None = None,
) -> CriticContext:
    answer_signals = extract_answer_signals(conversation)
    text = aggregate_unprompted_user_text(conversation)
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
    output_intent = _output_intent_with_committed_state(
        resolve_output_intent(text, answer_signals),
        planning_state,
    )
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
        aggregation_intent=(
            aggregation_intent
            if aggregation_intent is not None
            else (
                compile_context.aggregation_intent
                if compile_context is not None
                else "linear"
            )
        ),
        source_reader_required_field_names=frozenset(
            {
                field.name
                for field in (
                    compile_context.source_reader_required_fields
                    if compile_context is not None
                    else ()
                )
            }
            | (
                set(schema_leaf_property_names(compile_context.terminal_output_schema))
                if compile_context is not None
                and compile_context.terminal_output_schema is not None
                else set()
            )
        ),
        checkpoint_intents=(
            compile_context.checkpoint_intents if compile_context is not None else None
        ),
        result_contract=(
            derive_result_contract(planning_state)
            if planning_state is not None
            else None
        ),
        resolved_slots=(
            planning_state.resolved_slots if planning_state is not None else {}
        ),
        named_result_obligations=(
            planning_state.named_result_obligations
            if planning_state is not None
            else ()
        ),
        output_schema_evidence=(
            planning_state.output_schema_evidence
            if planning_state is not None
            else None
        ),
        resource_catalog=resource_catalog,
    )


def build_quality_feedback_from_critic_context(
    context: CriticContext,
    *,
    include_architecture: bool = False,
    include_edit_topology_advisories: bool = True,
) -> str | None:
    issues = [
        issue.remediation
        for issue in evaluate_critic_invariants(context)
        if include_architecture or issue.kind == "semantic"
        if include_edit_topology_advisories
        or issue.kind == "architecture"
        or not issue.edit_topology
    ]
    if not issues:
        return None
    return format_revision_feedback("Quality issues", issues)
