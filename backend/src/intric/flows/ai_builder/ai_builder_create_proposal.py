from __future__ import annotations

from typing import Any

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
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    mcp_resource_selection_values,
    mcp_selected_server_refs_from_values,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    ScopedStepModelNotice,
    resolve_scoped_step_model_revision_if_requested,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
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
from intric.main.logging import get_logger

logger = get_logger(__name__)
OUTLINE_FLOW_FORCED_TOOL_PROMPT = (
    "Your previous reply was prose only. "
    "Now call outline_flow with one complete semantic outline. "
    "Do not answer with prose."
)


def _latest_user_text(conversation: list[ConversationMessage]) -> str | None:
    for message in reversed(conversation):
        if message.role == "user" and isinstance(message.content, str):
            content = message.content.strip()
            if content:
                return content
    return None


async def process_outline_arguments(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    arguments: dict[str, Any],
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    planning_state: PlanningState | None = None,
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
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
        turn=turn,
        conversation=conversation,
        draft=draft,
        tool_call_id=tool_call_id,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        aggregation_intent=(
            compile_context.aggregation_intent
            if compile_context is not None
            else "linear"
        ),
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
    )


async def _process_create_draft(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    draft: FlowCreateDraft,
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    aggregation_intent: AggregationIntent = "linear",
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
) -> ToolProcessingResult:
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

    draft = normalize_create_draft_mechanics(
        draft,
        aggregation_intent=aggregation_intent,
    )
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
        spec = compile_create_draft(
            draft,
            aggregation_intent=aggregation_intent,
        )
    except Exception as error:
        logger.error("Create draft compilation failed: %s", error, exc_info=error)
        return ToolProcessingResult(
            feedback=f"Failed to compile {OUTLINE_FLOW_TOOL_NAME} draft: {error}",
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

    scoped_model_revision = resolve_scoped_step_model_revision_if_requested(
        context=plan_edit_context,
        prior_spec=(
            prior_plan_for_revision.spec
            if prior_plan_for_revision is not None
            else None
        ),
        latest_user_text=_latest_user_text(conversation),
        resource_catalog=resource_catalog,
    )
    if scoped_model_revision is not None:
        if isinstance(scoped_model_revision, ScopedStepModelNotice):
            return ToolProcessingResult(user_message=scoped_model_revision.message)
        prepared = prepare_compiled_spec_for_session(
            spec=scoped_model_revision.spec,
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
                    "Prepared scoped model revision spec validation failed: %s",
                    [error.message for error in prepared.validation.errors],
                )
            return ToolProcessingResult(
                feedback=prepared.failure_feedback,
                failure_kind="validation",
                failure_codes=frozenset(
                    error.code for error in prepared.validation.errors
                )
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

    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
            spec=spec,
            assumptions=tuple(draft.assumptions),
            plan_rationale=draft.plan_rationale,
            reasoning=None,
            validation=validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(spec, catalog=resource_catalog)
                if resource_catalog is not None
                else tuple()
            ),
            aggregation_intent=aggregation_intent,
        ),
    )
