from __future__ import annotations

from typing import Any

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_feedback import (
    format_create_intent_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposalContent,
    LintWarning,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    ProposalIntentArgumentError,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
    terminal_output_type_for_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    collect_flow_spec_resource_bindings,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_tools import parse_create_flow_intent_arguments
from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.main.logging import get_logger

logger = get_logger(__name__)
PROPOSE_FLOW_CREATE_FORCED_TOOL_PROMPT = (
    "Your previous reply was prose only. "
    "Now call propose_flow with one complete semantic flow intent. "
    "Do not answer with prose."
)
_NON_MODEL_REPAIRABLE_ARCHITECTURE_FAILURE_CODES = frozenset(
    {
        "assembly_unsupported_architecture_hints",
        "flow_input_schema_composite_bindings_unsupported",
        "flow_input_schema_target_missing",
        "section_writer_structured_source_ambiguous",
        "template_attachment_selection_invalid",
        "template_placeholder_unresolved",
    }
)


async def process_create_intent_arguments(
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
        intent = parse_create_flow_intent_arguments(arguments)
        compile_context = create_compile_context_from_planning_state(
            planning_state,
            ui_language=resolve_ui_language(conversation),
        )
        field_diagnostics: list[LintWarning] = []
        spec = compile_create_intent_to_spec(
            intent,
            context=compile_context,
            field_diagnostics=field_diagnostics,
        )
    except ProposalIntentArgumentError as error:
        logger.info(
            "ai_builder_create_intent_parse_failed session_id=%s tool_call_id=%s issues=%s",
            turn.session_id,
            tool_call_id,
            list(error.issues),
        )
        return ToolProcessingResult(
            feedback=f"Invalid propose_flow arguments: {error}",
            failure_kind="parse",
        )
    except AIBuilderArchitectureError as error:
        failure_code = _retryable_architecture_failure_code(error)
        if failure_code is not None:
            logger.info(
                "ai_builder_create_intent_architecture_rejected "
                "session_id=%s tool_call_id=%s failure_code=%s",
                turn.session_id,
                tool_call_id,
                failure_code,
            )
            return ToolProcessingResult(
                feedback=error.detail,
                failure_kind="validation",
                failure_codes=frozenset({failure_code}),
            )
        raise

    return await _process_create_spec(
        turn=turn,
        conversation=conversation,
        intent=intent,
        spec=spec,
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
        field_diagnostics=field_diagnostics,
    )


async def _process_create_spec(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    intent: CreateFlowIntent,
    spec: FlowDraftSpecCore,
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    aggregation_intent: AggregationIntent = "linear",
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    field_diagnostics: list[LintWarning] | None = None,
) -> ToolProcessingResult:
    prepared = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        terminal_output_type=terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=plan_edit_context,
            prior_plan=prior_plan_for_revision,
        ),
        ui_language=resolve_ui_language(conversation),
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
            feedback=format_create_intent_quality_feedback(scoped_revision_feedback),
            failure_kind="quality",
        )

    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
            content=FlowBuilderProposalContent(
                spec=spec,
                assumptions=intent.assumptions,
                lint_warnings=field_diagnostics or [],
                plan_rationale=intent.plan_rationale,
            ),
            validation=validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(spec, catalog=resource_catalog)
                if resource_catalog is not None
                else tuple()
            ),
            aggregation_intent=aggregation_intent,
        ),
    )


def _retryable_architecture_failure_code(
    error: AIBuilderArchitectureError,
) -> str | None:
    value = error.log_context.get("failure_code")
    if not isinstance(value, str) or not value:
        return None
    if value in _NON_MODEL_REPAIRABLE_ARCHITECTURE_FAILURE_CODES:
        return None
    return value
