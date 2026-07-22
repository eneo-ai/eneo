from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import OrderedEditProposal
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    evaluate_edit_topology_policy,
    resolve_ui_language,
    terminal_output_type_for_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    collect_flow_spec_resource_bindings,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.flow_authoring_spec import InputType
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
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
) -> ToolProcessingResult:
    if flow is None:
        return ToolProcessingResult(
            feedback="propose_flow requires an existing flow context.",
            failure_kind="validation",
        )

    try:
        proposal = OrderedEditProposal.model_validate(arguments)
    except ValidationError as exc:
        logger.warning("Failed to parse propose_flow edit arguments: %s", exc)
        return ToolProcessingResult(
            feedback=f"Invalid propose_flow arguments: {exc}",
            failure_kind="parse",
        )
    ui_language = resolve_ui_language(conversation)
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
            requested_primary_runtime_input_type=_requested_primary_runtime_input_type(
                planning_state=planning_state,
                conversation=conversation,
            ),
            ui_language=ui_language,
        )
    except BadRequestException as exc:
        return ToolProcessingResult(
            feedback=_format_edit_compilation_request_error(exc),
            failure_kind="validation",
        )
    except AssistantSnapshotResourceUnavailableError as exc:
        logger.warning(
            "Edit compilation failed because an assistant snapshot references "
            "an unavailable %s resource",
            exc.kind,
        )
        return ToolProcessingResult(
            feedback=(
                "A resource used by the existing flow is no longer available. "
                "Re-select the affected model or knowledge base "
                "and try again."
            ),
            failure_kind="validation",
        )

    compiled_spec = edit_result.spec
    prepared = prepare_compiled_spec_for_session(
        spec=compiled_spec,
        target_kind=TargetKind.EDIT,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        terminal_output_type=terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=plan_edit_context,
            prior_plan=prior_plan_for_revision,
        ),
        ui_language=ui_language,
    )
    if prepared.failure_feedback is not None:
        return ToolProcessingResult(
            feedback=prepared.failure_feedback,
            failure_kind="validation",
        )
    assert prepared.spec is not None
    assert prepared.validation is not None
    compiled_spec = prepared.spec
    validation = prepared.validation
    if validation.errors:
        error_messages = [err.message for err in validation.errors]
        return ToolProcessingResult(
            feedback=(
                "Compiled edit spec validation failed: " + "; ".join(error_messages)
            ),
            failure_kind="validation",
        )

    topology_policy = evaluate_edit_topology_policy(
        conversation=conversation,
        spec=compiled_spec,
        flow=flow,
        planning_state=planning_state,
        resource_catalog=resource_catalog,
    )
    if topology_policy.rejection_feedback is not None:
        return ToolProcessingResult(
            feedback=topology_policy.rejection_feedback,
            failure_kind="validation",
            failure_codes=topology_policy.failure_codes,
        )
    edit_approval = edit_result.approval.model_copy(
        update={
            "advisories": [
                *edit_result.approval.advisories,
                *topology_policy.advisories,
            ]
        }
    )

    scoped_revision_feedback = validate_scoped_plan_revision(
        context=plan_edit_context,
        prior_spec=(
            prior_plan_for_revision.spec
            if prior_plan_for_revision is not None
            else None
        ),
        proposed_spec=compiled_spec,
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
            "ai_builder_scoped_plan_edit_rejected session_id=%s target_step_ref=%s",
            turn.session_id,
            target_step_ref,
        )
        return ToolProcessingResult(
            feedback=scoped_revision_feedback,
            failure_kind="quality",
        )

    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
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
        ),
    )


def _requested_primary_runtime_input_type(
    *,
    planning_state: PlanningState | None,
    conversation: list[ConversationMessage],
) -> InputType | None:
    compile_context = create_compile_context_from_planning_state(
        planning_state,
        ui_language=resolve_ui_language(conversation),
    )
    if compile_context is None:
        return None
    return compile_context.runtime_input_type


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
