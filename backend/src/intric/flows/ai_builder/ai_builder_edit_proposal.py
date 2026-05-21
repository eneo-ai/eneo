from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, cast

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
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
from intric.flows.ai_builder.ai_builder_edit_repair import (
    should_attempt_description_repair,
    validate_repair_invariance,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_events import build_plan_event
from intric.flows.ai_builder.ai_builder_mcp_intent import mcp_selection_policy_feedback
from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    ConversationMessage,
    FlowDraftSpecCore,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    store_plan_and_update_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    format_contextual_quality_feedback,
    format_quality_feedback,
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
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
    from intric.flows.ai_builder.ai_builder_proposal_processor import (
        AIBuilderProposalProcessor,
    )
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)
EDIT_FLOW_FORCED_TOOL_PROMPT = (
    "Return one valid edit_flow tool call that keeps the flow coherent. "
    "Do not answer with prose."
)


async def process_edit_arguments(
    *,
    processor: AIBuilderProposalProcessor,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    flow: Flow | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
    assistant_metadata: dict[str, Any] | None = None,
    assistant_metadata_builder: Callable[[], dict[str, Any] | None] | None = None,
    proposal_success_recorder: Callable[[], None] | None = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    plan_edit_context: AIBuilderPlanEditContext | None = None,
    prior_plan_for_revision: BuilderPlan | None = None,
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

    compiled_spec = edit_result.compiled_spec
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

    mcp_clarification_events = await processor.mcp_clarification_events_if_needed(
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        spec=compiled_spec,
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
            spec=compiled_spec,
            catalog=resource_catalog,
        )
        if resource_catalog is not None
        else None
    )
    if mcp_policy_feedback is not None:
        logger.info(
            "ai_builder_edit_mcp_selection_policy_violation "
            "session_id=%s tool_call_id=%s",
            turn.session_id,
            tool_call_id,
        )

    current_provenance = _extract_description_provenance(flow.metadata_json)
    if should_attempt_description_repair(
        advisories=edit_result.advisories,
        current_description=flow.description,
        current_provenance=current_provenance,
    ):
        repaired_spec = await attempt_description_repair(
            processor=processor,
            compiled_spec=compiled_spec,
            flow=flow,
            llm_messages=[],
            tool_schemas=[],
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=min(max_output_tokens, 256),
        )
        if repaired_spec is not None:
            compiled_spec = repaired_spec
            edit_result = edit_result.model_copy(
                update={
                    "compiled_spec": compiled_spec,
                    "advisories": [
                        advisory
                        for advisory in edit_result.advisories
                        if advisory.code != "flow_description_update_required"
                    ],
                }
            )

    quality_feedback = format_quality_feedback(
        validation,
        quality_retry_warning_codes=processor.quality_retry_warning_codes,
    )
    contextual_quality_feedback = format_contextual_quality_feedback(
        conversation=conversation,
        spec=compiled_spec,
        flow=flow,
        resource_catalog=resource_catalog,
    )
    combined_quality_feedback = "\n\n".join(
        feedback
        for feedback in (
            mcp_policy_feedback,
            quality_feedback,
            contextual_quality_feedback,
        )
        if feedback
    )
    if combined_quality_feedback:
        logger.info(
            "ai_builder_edit_quality_feedback "
            "session_id=%s warning_codes=%s feedback=%s",
            turn.session_id,
            ",".join(warning.code for warning in validation.warnings) or "-",
            combined_quality_feedback[:1200],
        )
        return ToolProcessingResult(
            feedback=combined_quality_feedback,
            failure_kind="quality",
        )

    assumptions = list(draft.assumptions) if draft.assumptions else []
    serialized_edit_result = edit_result.model_dump(mode="json")
    stored_plan = await store_plan_and_update_conversation(
        repo=processor.repo,
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        assistant_content=assistant_content,
        assistant_metadata=_accepted_proposal_metadata(),
        tool_call_id=tool_call_id,
        tool_name=EDIT_FLOW_TOOL_NAME,
        arguments=arguments,
        spec=compiled_spec,
        assumptions=assumptions,
        plan_rationale=draft.plan_rationale,
        reasoning=None,
        validation=validation,
        resource_bindings=(
            collect_flow_spec_resource_bindings(compiled_spec, catalog=resource_catalog)
            if resource_catalog is not None
            else tuple()
        ),
        edit_result_json=serialized_edit_result,
        flow=flow,
    )
    return ToolProcessingResult(
        event=build_plan_event(
            plan_id=stored_plan.plan.id,
            envelope=stored_plan.envelope,
            edit_result=edit_result,
        ),
        new_planning_state_version=stored_plan.new_planning_state_version,
    )


async def attempt_description_repair(
    *,
    processor: AIBuilderProposalProcessor,
    compiled_spec: FlowDraftSpecCore,
    flow: Flow,
    llm_messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
) -> FlowDraftSpecCore | None:
    """Return a description-only repair when one LLM attempt preserves all other fields."""

    repair_prompt = (
        "The flow's input or output type changed but the description was not updated. "
        "Generate ONLY a new flow_description that accurately reflects the current flow. "
        f"Current flow name: {compiled_spec.flow_name}\n"
        f"Current description (stale): {compiled_spec.flow_description}\n"
        f"Steps: {', '.join(s.name for s in compiled_spec.steps)}\n"
        f"Entry input: {compiled_spec.steps[0].input_type.value if compiled_spec.steps else 'none'}\n"
        f"Terminal output: {compiled_spec.steps[-1].output_type.value if compiled_spec.steps else 'none'}\n"
        "Respond with ONLY the new description text, nothing else."
    )

    try:
        response = await processor.call_proposal_completion(
            messages=[{"role": "user", "content": repair_prompt}],
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            temperature=0.3,
        )
        new_description = (response.choices[0].message.content or "").strip()
        if not new_description:
            return None

        repaired = compiled_spec.model_copy(
            update={"flow_description": new_description}
        )
        if not validate_repair_invariance(compiled_spec, repaired):
            logger.warning(
                "Description repair changed non-description fields, rejecting"
            )
            return None

        return repaired
    except Exception as exc:
        logger.warning("Description repair failed: %s", exc)
        return None


def _bind_process_edit_arguments(
    processor: AIBuilderProposalProcessor,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
) -> Callable[[ToolRetryInvocation], Awaitable[ToolProcessingResult]]:
    async def _bound_process_edit_arguments(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return await process_edit_arguments(
            processor=processor,
            turn=invocation.turn,
            conversation=invocation.conversation,
            new_messages_start=invocation.new_messages_start,
            arguments=invocation.arguments,
            assistant_content=invocation.assistant_content,
            tool_call_id=invocation.tool_call_id,
            available_model_refs=invocation.available_model_refs,
            available_kb_refs=invocation.available_kb_refs,
            flow=invocation.flow,
            assistant_snapshots=assistant_snapshots,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            assistant_metadata=invocation.assistant_metadata,
            resource_catalog=invocation.resource_catalog,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )

    return _bound_process_edit_arguments


def edit_flow_retry_config(
    *,
    processor: AIBuilderProposalProcessor,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
) -> ToolRetryConfig:
    return ToolRetryConfig(
        target_tool_name=EDIT_FLOW_TOOL_NAME,
        forced_tool_prompt=EDIT_FLOW_FORCED_TOOL_PROMPT,
        process_tool_invocation=_bind_process_edit_arguments(
            processor,
            assistant_snapshots=assistant_snapshots,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        ),
    )


def _extract_description_provenance(
    metadata_json: dict[str, Any] | None,
) -> DescriptionProvenance | None:
    """Extract description provenance from flow metadata, if present."""

    if not isinstance(metadata_json, dict):
        return None
    ai_builder = metadata_json.get("ai_builder")
    if not isinstance(ai_builder, dict):
        return None
    desc_raw = cast(dict[str, Any], ai_builder).get("description")
    if not isinstance(desc_raw, dict):
        return None
    try:
        return DescriptionProvenance.model_validate(desc_raw)
    except Exception:
        return None
