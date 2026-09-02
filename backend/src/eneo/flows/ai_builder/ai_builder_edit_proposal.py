from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    model_correctable_architecture_failure_code,
    terminal_architecture_failure,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
    validate_scoped_edit_proposal,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    capture_rejected_proposal_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import OrderedEditProposal
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    evaluate_edit_topology_policy,
    terminal_output_type_for_edit_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_MODEL_FAILURE_CODE,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    CorrectableFailure,
    PreparationOutcome,
    ProposalReady,
    TerminalFailure,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    collect_flow_spec_resource_bindings,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)
PROPOSE_FLOW_EDIT_FORCED_TOOL_PROMPT = (
    "Return one valid propose_flow tool call that keeps the flow coherent. "
    "Do not answer with prose."
)


async def process_edit_arguments(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    arguments: dict[str, Any],
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    flow: Flow | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    planning_state: PlanningState | None = None,
    plan_edit_context: ResolvedAIBuilderEditContext | None = None,
    prior_spec_for_revision: FlowDraftSpecCore | None = None,
    compile_context: CreateCompileContext | None = None,
) -> PreparationOutcome:
    if flow is None:
        # A precondition of the edit session, not something the model wrote.
        return TerminalFailure(
            kind="validation",
            message="propose_flow requires an existing flow context.",
            code=AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED,
            phase=AIBuilderErrorPhase.PROPOSAL,
        )

    model_arguments: dict[str, Any] = dict(arguments)
    try:
        raw_form_fields = model_arguments.get("form_fields")
        if isinstance(raw_form_fields, list):
            normalized_form_fields: list[Any] = []
            for field in cast(list[Any], raw_form_fields):
                normalized_form_fields.append(
                    {
                        **cast(dict[str, Any], field),
                        "provenance": "model_proposed",
                    }
                    if isinstance(field, dict)
                    else field
                )
            model_arguments["form_fields"] = normalized_form_fields
        proposal = _apply_server_owned_input_fields(
            OrderedEditProposal.model_validate(model_arguments),
            planning_state=planning_state,
        )
    except ValidationError as exc:
        logger.warning("Failed to parse propose_flow edit arguments: %s", exc)
        capture_rejected_proposal_arguments(
            model_arguments,
            session_id=str(turn.session_id),
            issues=[str(exc)],
        )
        return CorrectableFailure(
            feedback=f"Invalid propose_flow arguments: {exc}",
            kind="parse",
            codes=frozenset({PROPOSAL_PARSE_MODEL_FAILURE_CODE}),
        )
    scoped_proposal_feedback = validate_scoped_edit_proposal(
        context=plan_edit_context,
        proposal=proposal,
    )
    if scoped_proposal_feedback is not None:
        return CorrectableFailure(feedback=scoped_proposal_feedback, kind="quality")
    ui_language = compile_context.ui_language if compile_context is not None else None
    try:
        edit_result = compile_edit_proposal(
            proposal,
            current_steps=list(flow.steps),
            base_flow_revision=flow.draft_revision,
            flow_name=flow.name,
            flow_description=flow.description,
            current_metadata_json=flow.metadata_json,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
            requested_primary_runtime_input_type=(
                compile_context.runtime_input_type
                if compile_context is not None
                else None
            ),
            ui_language=ui_language,
            selected_template_count=(
                compile_context.selected_template_count
                if compile_context is not None
                else None
            ),
            selected_template_placeholders=(
                compile_context.selected_template_placeholders
                if compile_context is not None
                else None
            ),
        )
    except BadRequestException as exc:
        return CorrectableFailure(
            feedback=_format_edit_compilation_request_error(exc), kind="validation"
        )
    except AIBuilderArchitectureError as exc:
        failure_code = model_correctable_architecture_failure_code(exc)
        if failure_code is None:
            return terminal_architecture_failure(exc)
        return CorrectableFailure(
            feedback=exc.detail,
            kind="validation",
            codes=frozenset({failure_code}),
        )
    except AssistantSnapshotResourceUnavailableError as exc:
        logger.warning(
            "Edit compilation failed because an assistant snapshot references "
            "an unavailable %s resource",
            exc.kind,
        )
        # Only the user can re-select the resource; another model call cannot.
        return TerminalFailure(
            kind="validation",
            message=(
                "A resource used by the existing flow is no longer available. "
                "Re-select the affected model or knowledge base and try again."
            ),
            code=AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDING_UNAVAILABLE,
            phase=AIBuilderErrorPhase.PROPOSAL,
            details={"resource_kind": str(exc.kind)},
        )

    compiled_spec = edit_result.spec
    prepared = prepare_compiled_spec_for_session(
        spec=compiled_spec,
        target_kind=TargetKind.EDIT,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        terminal_output_type=terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=plan_edit_context,
            prior_spec=prior_spec_for_revision,
        ),
        ui_language=ui_language,
    )
    if prepared.failure_feedback is not None:
        return CorrectableFailure(feedback=prepared.failure_feedback, kind="validation")
    assert prepared.spec is not None
    assert prepared.validation is not None
    compiled_spec = prepared.spec
    validation = prepared.validation
    if validation.errors:
        error_messages = [err.message for err in validation.errors]
        return CorrectableFailure(
            feedback=(
                "Compiled edit spec validation failed: " + "; ".join(error_messages)
            ),
            kind="validation",
            codes=frozenset(error.code for error in validation.errors),
        )

    topology_policy = evaluate_edit_topology_policy(
        conversation=conversation,
        spec=compiled_spec,
        flow=flow,
        planning_state=planning_state,
        resource_catalog=resource_catalog,
        compile_context=compile_context,
    )
    if topology_policy.rejection_feedback is not None:
        return CorrectableFailure(
            feedback=topology_policy.rejection_feedback,
            kind="validation",
            codes=topology_policy.failure_codes,
        )
    edit_approval = edit_result.approval.model_copy(
        update={
            "scoped_target_existing_step_ref": (
                plan_edit_context.target_existing_step_ref
                if plan_edit_context is not None and plan_edit_context.scope == "step"
                else None
            ),
            "scoped_target_plan_step_ref": (
                plan_edit_context.target_plan_step_ref
                if plan_edit_context is not None and plan_edit_context.scope == "step"
                else None
            ),
            "advisories": [
                *edit_result.approval.advisories,
                *topology_policy.advisories,
            ],
        }
    )

    scoped_rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.EDIT,
        context=plan_edit_context,
        prior_spec=prior_spec_for_revision,
        proposed_spec=compiled_spec,
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
            "ai_builder_scoped_plan_edit_rejected session_id=%s target_step_ref=%s",
            turn.session_id,
            target_step_ref,
        )
        return CorrectableFailure(feedback=scoped_rejection.feedback, kind="quality")

    return ProposalReady(
        compiled=CompiledProposal(
            content=FlowBuilderProposalContent(
                spec=compiled_spec,
                assumptions=proposal.assumptions,
                plan_rationale=proposal.plan_rationale,
                edit=edit_approval,
            ),
            validation=validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(
                    compiled_spec, catalog=resource_catalog
                )
                if resource_catalog is not None
                else tuple()
            ),
            aggregation_intent=(
                compile_context.aggregation_intent
                if compile_context is not None
                else "linear"
            ),
        ),
    )


def _apply_server_owned_input_fields(
    proposal: OrderedEditProposal,
    *,
    planning_state: PlanningState | None,
) -> OrderedEditProposal:
    if planning_state is None or not planning_state.input_fields:
        return proposal
    server_fields = {
        record.value.variable_name: record.value
        for record in planning_state.input_fields
    }
    if proposal.form_fields is None or "form_fields" not in proposal.model_fields_set:
        return proposal.model_copy(update={"form_fields": list(server_fields.values())})
    projected_fields = [
        server_fields.get(field.variable_name, field) for field in proposal.form_fields
    ]
    projected_names = {field.variable_name for field in projected_fields}
    projected_fields.extend(
        record.value
        for record in planning_state.input_fields
        if record.value.variable_name not in projected_names
    )
    return proposal.model_copy(update={"form_fields": projected_fields})


def _format_edit_compilation_request_error(exc: BadRequestException) -> str:
    if exc.code != "invalid_existing_step_ref":
        return f"Failed to compile edit: {exc}"
    context = exc.context or {}
    missing_refs = context.get("missing_refs")
    if isinstance(missing_refs, list) and missing_refs:
        return (
            "Edit validation failed: every existing step must appear in steps "
            "or be listed in removed_existing_step_refs. Missing refs: "
            f"{missing_refs}."
        )
    overlap_refs = context.get("overlap_refs")
    if isinstance(overlap_refs, list) and overlap_refs:
        return (
            "Edit validation failed: refs cannot appear in both steps and "
            "removed_existing_step_refs. Overlap refs: "
            f"{overlap_refs}."
        )
    return f"Edit validation failed: {exc}"
