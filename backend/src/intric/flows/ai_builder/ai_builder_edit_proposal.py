from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_mechanics import fill_edit_draft_mechanics
from intric.flows.ai_builder.ai_builder_edit_models import FlowEditDraft
from intric.flows.ai_builder.ai_builder_edit_normalizer import (
    canonicalize_duplicate_modify_operations,
    format_duplicate_modify_conflicts,
    normalize_edit_draft_mechanics,
    normalize_loose_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    canonicalize_edit_draft_resources,
    collect_flow_spec_resource_bindings,
    format_resource_resolution_feedback,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)
EDIT_FLOW_FORCED_TOOL_PROMPT = (
    "Return one valid edit_flow tool call that keeps the flow coherent. "
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
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
) -> ToolProcessingResult:
    if flow is None:
        return ToolProcessingResult(
            feedback="edit_flow requires an existing flow context.",
            failure_kind="validation",
        )

    try:
        draft = FlowEditDraft.model_validate(normalize_loose_edit_arguments(arguments))
    except Exception as exc:
        logger.warning("Failed to parse edit_flow arguments: %s", exc)
        return ToolProcessingResult(
            feedback=f"Invalid edit_flow arguments: {exc}",
            failure_kind="parse",
        )

    if resource_catalog is not None:
        draft, resolution_issues = canonicalize_edit_draft_resources(
            draft,
            catalog=resource_catalog,
        )
        if resolution_issues:
            return ToolProcessingResult(
                feedback=format_resource_resolution_feedback(resolution_issues),
                failure_kind="validation",
            )

    canonicalized = canonicalize_duplicate_modify_operations(draft)
    if canonicalized.conflicts:
        return ToolProcessingResult(
            feedback=format_duplicate_modify_conflicts(canonicalized.conflicts),
            failure_kind="validation",
        )
    draft = canonicalized.draft

    draft = normalize_edit_draft_mechanics(
        draft,
        current_steps=list(flow.steps),
        current_metadata_json=flow.metadata_json,
    )
    draft = fill_edit_draft_mechanics(
        draft,
        current_steps=list(flow.steps),
    )
    valid_step_refs = [f"existing_step_{step.step_order}" for step in flow.steps]
    edit_validation = validate_edit_draft(
        draft,
        valid_step_refs,
        current_steps=list(flow.steps),
        current_metadata_json=flow.metadata_json,
    )
    if edit_validation.errors:
        error_messages = [err.message for err in edit_validation.errors]
        logger.info("Edit draft validation failed: %s", error_messages)
        return ToolProcessingResult(
            feedback=f"Edit validation failed: {'; '.join(error_messages)}",
            failure_kind="validation",
        )

    try:
        edit_result = compile_edit_draft(
            draft,
            current_steps=list(flow.steps),
            base_flow_revision=flow.draft_revision,
            flow_name=flow.name,
            flow_description=flow.description,
            current_metadata_json=flow.metadata_json,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
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
                "Re-select the affected model, knowledge base, or MCP resource "
                "and try again."
            ),
            failure_kind="validation",
        )
    except Exception as exc:
        logger.error("Edit compilation failed: %s", exc, exc_info=True)
        return ToolProcessingResult(
            feedback=f"Failed to compile edit: {exc}",
            failure_kind="validation",
        )

    compiled_spec = edit_result.spec
    prepared = prepare_compiled_spec_for_session(
        spec=compiled_spec,
        target_kind=TargetKind.EDIT,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        valid_existing_step_refs=valid_step_refs,
        terminal_output_type=terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=plan_edit_context,
            prior_plan=prior_plan_for_revision,
        ),
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
            feedback=format_create_quality_feedback(scoped_revision_feedback),
            failure_kind="quality",
        )

    assumptions = list(draft.assumptions) if draft.assumptions else []
    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
            spec=compiled_spec,
            assumptions=tuple(assumptions),
            plan_rationale=draft.plan_rationale,
            reasoning=None,
            validation=validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(
                    compiled_spec, catalog=resource_catalog
                )
                if resource_catalog is not None
                else tuple()
            ),
            edit=edit_result.approval,
        ),
    )
