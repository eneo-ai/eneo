from __future__ import annotations

from typing import Any

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import CreateCompileContext
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_create_feedback import (
    format_create_intent_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    FlowBuilderProposalContent,
    LintWarning,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    scoped_revision_out_of_reach_message,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    capture_rejected_proposal_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    ProposalIntentArgumentError,
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_MODEL_FAILURE_CODE,
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
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, OutputType
from eneo.main.logging import get_logger

logger = get_logger(__name__)


PROPOSE_FLOW_CREATE_FORCED_TOOL_PROMPT = (
    "Your previous reply was prose only. "
    "Now call propose_flow with one complete semantic flow intent. "
    "Do not answer with prose."
)
_NON_MODEL_REPAIRABLE_ARCHITECTURE_FAILURE_CODES = frozenset(
    {
        "checkpoint_transcript_producer_missing",
        "assembly_unsupported_architecture_hints",
        "assembly_document_report_compose_topology_missing",
        "flow_input_schema_composite_bindings_unsupported",
        "flow_input_schema_target_missing",
        # A dropped obligation is a compiler defect against a name the user
        # already confirmed. The compiled-postcondition breach of the
        # attested result contract is the same class: admission verified the
        # model's declaration, so a violation surfacing after compilation is
        # a server defect. No model can repair a server bug, and asking one
        # to try would spend the turn's budget hiding it.
        "attested_result_contract_broken",
        "section_writer_structured_source_ambiguous",
        "terminal_output_type_mismatch",
        "template_attachment_selection_invalid",
        "template_attachment_unreadable",
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
    plan_edit_context: ResolvedAIBuilderEditContext | None = None,
    prior_spec_for_revision: FlowDraftSpecCore | None = None,
    compile_context: CreateCompileContext | None = None,
    obligation_projection: ProposalObligationProjection | None = None,
) -> ToolProcessingResult:
    try:
        intent = parse_create_flow_intent_arguments(
            arguments,
            obligation_projection=obligation_projection,
        )
        field_diagnostics: list[LintWarning] = []
        spec = compile_create_intent_to_spec(
            intent,
            context=compile_context,
            field_diagnostics=field_diagnostics,
            obligation_projection=obligation_projection,
        )
    except ProposalIntentArgumentError as error:
        logger.info(
            "ai_builder_create_intent_parse_failed session_id=%s tool_call_id=%s issues=%s",
            turn.session_id,
            tool_call_id,
            list(error.issues),
        )
        capture_rejected_proposal_arguments(
            arguments,
            session_id=str(turn.session_id),
            issues=list(error.issues),
        )
        return ToolProcessingResult(
            feedback=f"Invalid propose_flow arguments: {error}",
            failure_kind="parse",
            failure_codes=frozenset({PROPOSAL_PARSE_MODEL_FAILURE_CODE}),
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
            capture_rejected_proposal_arguments(
                arguments,
                session_id=str(turn.session_id),
                issues=[failure_code, error.detail],
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
        committed_terminal_output_type=(
            compile_context.final_output_type if compile_context is not None else None
        ),
        plan_edit_context=plan_edit_context,
        prior_spec_for_revision=prior_spec_for_revision,
        field_diagnostics=field_diagnostics,
        ui_language=(
            compile_context.ui_language if compile_context is not None else None
        ),
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
    aggregation_intent: AggregationIntent,
    committed_terminal_output_type: OutputType | None,
    plan_edit_context: ResolvedAIBuilderEditContext | None = None,
    prior_spec_for_revision: FlowDraftSpecCore | None = None,
    field_diagnostics: list[LintWarning] | None = None,
    ui_language: str | None = None,
) -> ToolProcessingResult:
    prepared = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        terminal_output_type=committed_terminal_output_type,
        ui_language=ui_language,
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

    scoped_rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=plan_edit_context,
        prior_spec=prior_spec_for_revision,
        proposed_spec=spec,
    )
    if scoped_rejection is not None:
        target_step_ref = (
            (
                plan_edit_context.target_plan_step_ref
                or plan_edit_context.target_existing_step_ref
            )
            if plan_edit_context is not None
            else None
        )
        logger.info(
            "ai_builder_scoped_plan_revision_rejected session_id=%s "
            "target_step_ref=%s reason=%s",
            turn.session_id,
            target_step_ref,
            scoped_rejection.reason,
        )
        if scoped_rejection.reason == "unrelated_compiled_step_changed":
            # A create revision returns the whole plan but is shown only each
            # other step's name and types, so it cannot reproduce their
            # compiled content and no repair can reach this bar. The user gets
            # one answer naming the scope that can carry the change instead of
            # three more provider calls that fail the same way.
            return ToolProcessingResult(
                terminal_answer=scoped_revision_out_of_reach_message(
                    ui_language=ui_language
                )
            )
        return ToolProcessingResult(
            feedback=format_create_intent_quality_feedback(scoped_rejection.feedback),
            failure_kind="quality",
        )

    # Diagnostics travel on validation: the storage boundary is the sole
    # deriver of content.lint_warnings and refuses content that pre-sets
    # them — writing them here killed every create whose compile dropped a
    # runtime field, after the provider was already paid.
    if field_diagnostics:
        validation.warnings.extend(field_diagnostics)
    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
            content=FlowBuilderProposalContent(
                spec=spec,
                assumptions=intent.assumptions,
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
