from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
)
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_critic_feedback,
    format_create_outline_quality_feedback,
    format_create_validation_feedback,
)
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_create_outline import (
    OutlineFlowArgumentError,
    attach_selected_mcp_refs_to_explicit_outline_steps,
    compile_outline_to_create_draft,
    outline_compile_context_from_planning_state,
    runtime_metadata_state_from_planning_state,
    safe_validation_issues,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_critic_invariants import (
    enforce_architecture_critic_invariants,
    evaluate_critic_invariants,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_events import build_plan_event
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    mcp_resource_selection_values,
    mcp_selected_server_refs_from_values,
    mcp_selection_policy_feedback,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_critic_context,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    format_validation_feedback,
    store_plan_and_update_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    format_quality_feedback,
    resolve_ui_language,
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalToolDeps,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    canonicalize_create_draft_resources,
    collect_flow_spec_resource_bindings,
    format_resource_resolution_feedback,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    extract_runtime_input_field_hints,
    runtime_metadata_allows_input_fields,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import (
    OUTLINE_FLOW_TOOL_NAME,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)
OUTLINE_FLOW_FORCED_TOOL_PROMPT = (
    "Your previous reply was prose only. "
    "Now call outline_flow with one complete semantic outline. "
    "Do not answer with prose."
)


async def process_outline_arguments(
    *,
    proposal_deps: ProposalToolDeps,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    assistant_metadata: dict[str, Any] | None = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    flow: "Flow | None" = None,
    planning_state: PlanningState | None = None,
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    assistant_metadata_builder: Callable[[], dict[str, Any] | None] | None = None,
    proposal_success_recorder: Callable[[], None] | None = None,
) -> ToolProcessingResult:
    try:
        outline = parse_outline_flow_arguments(arguments)
        if resource_catalog is not None:
            outline = attach_selected_mcp_refs_to_explicit_outline_steps(
                outline,
                selected_server_refs=mcp_selected_server_refs_from_values(
                    mcp_resource_selection_values(conversation)
                ),
                catalog=resource_catalog,
            )
        runtime_metadata_state = runtime_metadata_state_from_planning_state(
            planning_state
        )
        runtime_input_field_hints = (
            extract_runtime_input_field_hints(
                aggregate_freeform_user_text(conversation)
            )
            if runtime_metadata_allows_input_fields(runtime_metadata_state)
            else ()
        )
        compile_context = outline_compile_context_from_planning_state(
            planning_state,
            ui_language=resolve_ui_language(conversation),
            runtime_input_field_hints=runtime_input_field_hints,
        )
        draft = compile_outline_to_create_draft(
            outline,
            context=compile_context,
        )
    except OutlineFlowArgumentError as error:
        logger.info(
            "ai_builder_outline_parse_failed session_id=%s tool_call_id=%s issues=%s",
            turn.session_id,
            tool_call_id,
            list(error.issues),
        )
        return ToolProcessingResult(
            feedback=f"Invalid outline_flow arguments: {error}",
            failure_kind="parse",
        )
    except AIBuilderArchitectureError:
        raise
    except Exception as error:
        issues = (
            list(safe_validation_issues(error))
            if isinstance(error, ValidationError)
            else None
        )
        logger.info(
            "ai_builder_outline_compile_failed session_id=%s tool_call_id=%s error_type=%s issues=%s",
            turn.session_id,
            tool_call_id,
            type(error).__name__,
            issues,
        )
        detail = "; ".join(issues) if issues else str(error)
        return ToolProcessingResult(
            feedback=f"Invalid outline_flow arguments: {detail}",
            failure_kind="parse",
        )

    return await _process_create_draft(
        proposal_deps=proposal_deps,
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        draft=draft,
        arguments=arguments,
        assistant_content=assistant_content,
        assistant_metadata=assistant_metadata,
        tool_call_id=tool_call_id,
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        flow=flow,
        aggregation_intent=(
            compile_context.aggregation_intent
            if compile_context is not None
            else "linear"
        ),
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        assistant_metadata_builder=assistant_metadata_builder,
        proposal_success_recorder=proposal_success_recorder,
    )


async def _process_create_draft(
    *,
    proposal_deps: ProposalToolDeps,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    draft: FlowCreateDraft,
    arguments: dict[str, Any],
    assistant_content: str,
    assistant_metadata: dict[str, Any] | None,
    tool_call_id: str,
    tool_name: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    flow: "Flow | None",
    aggregation_intent: AggregationIntent = "linear",
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    assistant_metadata_builder: Callable[[], dict[str, Any] | None] | None = None,
    proposal_success_recorder: Callable[[], None] | None = None,
) -> ToolProcessingResult:
    metadata_built = False

    def _accepted_proposal_metadata() -> dict[str, Any] | None:
        nonlocal assistant_metadata, metadata_built
        if not metadata_built:
            if proposal_success_recorder is not None:
                proposal_success_recorder()
            if assistant_metadata_builder is not None:
                assistant_metadata = assistant_metadata_builder()
            metadata_built = True
        return assistant_metadata

    if resource_catalog is not None:
        draft, resolution_issues = canonicalize_create_draft_resources(
            draft,
            catalog=resource_catalog,
        )
        if resolution_issues:
            return ToolProcessingResult(
                feedback=format_resource_resolution_feedback(resolution_issues),
                failure_kind="validation",
            )

    draft = normalize_create_draft_mechanics(draft)
    create_validation = validate_create_draft(draft)
    if create_validation.errors:
        logger.info(
            "Create draft validation failed: %s",
            [error.message for error in create_validation.errors],
        )
        return ToolProcessingResult(
            feedback=format_create_validation_feedback(create_validation),
            failure_kind="validation",
            failure_codes=frozenset(error.code for error in create_validation.errors),
        )

    try:
        spec = compile_create_draft(draft)
    except Exception as error:
        logger.error("Create draft compilation failed: %s", error, exc_info=error)
        return ToolProcessingResult(
            feedback=f"Failed to compile {tool_name} draft: {error}",
            failure_kind="validation",
        )

    prepared = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        valid_existing_step_refs=None,
        terminal_output_type=terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=plan_edit_context,
            prior_plan=prior_plan_for_revision,
        ),
    )
    if prepared.failure_feedback is not None:
        if prepared.validation is not None and prepared.validation.errors:
            logger.info(
                "Prepared create spec validation failed: %s",
                [error.message for error in prepared.validation.errors],
            )
        return ToolProcessingResult(
            feedback=prepared.failure_feedback,
            failure_kind="validation",
            failure_codes=frozenset(error.code for error in prepared.validation.errors)
            if prepared.validation is not None
            else frozenset(),
        )
    assert prepared.spec is not None
    assert prepared.validation is not None
    spec = prepared.spec
    validation = prepared.validation

    scoped_revision_feedback = validate_scoped_plan_revision(
        context=plan_edit_context,
        prior_spec=(
            prior_plan_for_revision.spec
            if prior_plan_for_revision is not None
            else None
        ),
        proposed_spec=spec,
    )
    if scoped_revision_feedback is not None:
        target_step_ref = (
            (
                plan_edit_context.target_plan_step_ref
                or plan_edit_context.target_existing_step_ref
            )
            if plan_edit_context is not None
            else None
        )
        logger.info(
            "ai_builder_scoped_plan_revision_rejected session_id=%s target_step_ref=%s",
            turn.session_id,
            target_step_ref,
        )
        return ToolProcessingResult(
            feedback=format_create_outline_quality_feedback(scoped_revision_feedback),
            failure_kind="quality",
        )

    mcp_clarification_events = await proposal_deps.mcp_clarification_events_if_needed(
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        spec=spec,
        resource_catalog=resource_catalog,
        flow=flow,
        assistant_metadata_builder=_accepted_proposal_metadata,
    )
    if mcp_clarification_events:
        return ToolProcessingResult(
            event=mcp_clarification_events.events[0],
            events=tuple(mcp_clarification_events.events[1:]),
            new_planning_state_version=(
                mcp_clarification_events.new_planning_state_version
            ),
        )
    mcp_policy_feedback = (
        mcp_selection_policy_feedback(
            conversation=conversation,
            spec=spec,
            catalog=resource_catalog,
        )
        if resource_catalog is not None
        else None
    )
    if mcp_policy_feedback is not None:
        logger.info(
            "ai_builder_mcp_selection_policy_violation session_id=%s tool_call_id=%s",
            turn.session_id,
            tool_call_id,
        )

    if not validation.valid:
        logger.info(
            "Compiled create spec validation failed: %s",
            [error.message for error in validation.errors],
        )
        quality_hint = format_quality_feedback(
            validation,
            quality_retry_warning_codes=proposal_deps.quality_retry_warning_codes,
        )
        contextual_hint = format_create_contextual_quality_feedback(
            conversation=conversation,
            spec=spec,
            aggregation_intent=aggregation_intent,
            resource_catalog=resource_catalog,
        )
        hard_feedback = format_validation_feedback(
            spec=spec,
            errors=validation.errors,
        )
        combined_feedback = "\n\n".join(
            feedback
            for feedback in (
                hard_feedback,
                mcp_policy_feedback,
                quality_hint,
                contextual_hint,
            )
            if feedback
        )
        combined_feedback = format_create_outline_quality_feedback(combined_feedback)
        return ToolProcessingResult(
            feedback=combined_feedback,
            failure_kind="validation",
            failure_codes=frozenset(error.code for error in validation.errors),
        )

    quality_feedback = format_quality_feedback(
        validation,
        quality_retry_warning_codes=proposal_deps.quality_retry_warning_codes,
    )
    contextual_quality_feedback = format_create_contextual_quality_feedback(
        conversation=conversation,
        spec=spec,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
    )
    combined_quality_feedback = (
        "\n\n".join(
            feedback
            for feedback in (
                mcp_policy_feedback,
                quality_feedback,
                contextual_quality_feedback,
            )
            if feedback is not None
        )
        or None
    )
    combined_quality_feedback = format_create_outline_quality_feedback(
        combined_quality_feedback
    )
    if combined_quality_feedback is not None:
        return ToolProcessingResult(
            feedback=combined_quality_feedback,
            failure_kind="quality",
        )

    stored_plan = await store_plan_and_update_conversation(
        repo=proposal_deps.repo,
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        assistant_content=assistant_content,
        assistant_metadata=_accepted_proposal_metadata(),
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        spec=spec,
        assumptions=list(draft.assumptions),
        plan_rationale=draft.plan_rationale,
        reasoning=None,
        validation=validation,
        resource_bindings=(
            collect_flow_spec_resource_bindings(spec, catalog=resource_catalog)
            if resource_catalog is not None
            else tuple()
        ),
        flow=flow,
    )
    return ToolProcessingResult(
        event=build_plan_event(
            plan_id=stored_plan.plan.id,
            envelope=stored_plan.envelope,
        ),
        new_planning_state_version=stored_plan.new_planning_state_version,
    )


def format_create_contextual_quality_feedback(
    *,
    conversation: list[ConversationMessage],
    spec: FlowDraftSpecCore,
    aggregation_intent: AggregationIntent,
    resource_catalog: AIBuilderResourceCatalog | None,
) -> str | None:
    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=None,
        aggregation_intent=aggregation_intent,
        resource_catalog=resource_catalog,
    )
    enforce_architecture_critic_invariants(context)
    return format_create_critic_feedback(evaluate_critic_invariants(context))


def outline_flow_retry_config(
    *,
    proposal_deps: ProposalToolDeps,
    planning_state: PlanningState | None = None,
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
) -> ToolRetryConfig:
    return ToolRetryConfig(
        target_tool_name=OUTLINE_FLOW_TOOL_NAME,
        forced_tool_prompt=OUTLINE_FLOW_FORCED_TOOL_PROMPT,
        process_tool_invocation=_bind_process_outline_arguments(
            proposal_deps=proposal_deps,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        ),
    )


def _bind_process_outline_arguments(
    proposal_deps: ProposalToolDeps,
    *,
    planning_state: PlanningState | None,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
) -> Callable[[ToolRetryInvocation], Awaitable[ToolProcessingResult]]:
    async def _bound_process_outline_arguments(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return await process_outline_arguments(
            proposal_deps=proposal_deps,
            turn=invocation.turn,
            conversation=invocation.conversation,
            new_messages_start=invocation.new_messages_start,
            arguments=invocation.arguments,
            assistant_content=invocation.assistant_content,
            tool_call_id=invocation.tool_call_id,
            available_model_refs=invocation.available_model_refs,
            available_kb_refs=invocation.available_kb_refs,
            assistant_metadata=invocation.assistant_metadata,
            resource_catalog=invocation.resource_catalog,
            flow=invocation.flow,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )

    return _bound_process_outline_arguments
