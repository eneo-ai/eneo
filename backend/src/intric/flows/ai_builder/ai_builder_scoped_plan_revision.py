"""Own deterministic selected-step proposal revisions that bypass the LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    make_provider_safe_server_tool_call_id,
)
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_intent_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposalContent,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from intric.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from intric.flows.ai_builder.ai_builder_events import build_text_event
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    ScopedStepNotice,
    resolve_scoped_step_revision_if_requested,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    collect_flow_spec_resource_bindings,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScopedPlanRevisionRequest:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    request_id: str
    usage_tracker: ProposalTurnTelemetry | None
    assistant_metadata: dict[str, object] | None = None
    flow: "Flow | None" = None


@dataclass(frozen=True)
class ScopedPlanRevisionOutcome:
    events: tuple[AIBuilderStreamEvent, ...] = ()
    fall_through_to_active_submission: bool = False


async def run_scoped_plan_revision_attempt(
    *,
    request: ScopedPlanRevisionRequest,
    finalizer: CompiledProposalFinalizer,
) -> ScopedPlanRevisionOutcome | None:
    if request.flow is not None:
        return None

    result = process_scoped_step_revision_if_requested(
        conversation=request.conversation,
        available_model_refs=request.available_model_refs,
        available_kb_refs=request.available_kb_refs,
        resource_catalog=request.resource_catalog,
        plan_edit_context=request.plan_edit_context,
        prior_plan_for_revision=request.prior_plan_for_revision,
    )
    if result is None:
        return None
    if result.compiled_proposal is None:
        if result.feedback is not None:
            return ScopedPlanRevisionOutcome(
                events=(
                    build_ai_builder_error_event(
                        message=(
                            "The selected step change could not be applied to "
                            "the current plan. Refresh the plan and try again."
                        ),
                        code=AIBuilderErrorCode.BAD_REQUEST,
                        phase=AIBuilderErrorPhase.PROPOSAL,
                        request_id=request.request_id,
                        details={
                            "failure_kind": result.failure_kind or "unknown",
                        },
                    ),
                )
            )
        return _outcome_from_processing_result(result)

    finalized = await finalizer.finalize_compiled_proposal(
        CompiledProposalFinalizationRequest(
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=TargetKind.CREATE,
            arguments={
                "plan_rationale": result.compiled_proposal.content.plan_rationale or "",
                "revision_kind": "scoped_step_direct",
            },
            assistant_content=scoped_step_revision_assistant_text(request.conversation),
            assistant_metadata=request.assistant_metadata,
            tool_call_id=make_provider_safe_server_tool_call_id(
                kind="scoped_step_revision",
                stable_key=request.request_id,
            ),
            metadata_tool_call=None,
            compiled=result.compiled_proposal,
            resource_catalog=request.resource_catalog,
            flow=request.flow,
            request_id=request.request_id,
            usage_tracker=request.usage_tracker,
        )
    )
    return _outcome_from_processing_result(finalized)


def process_scoped_step_revision_if_requested(
    *,
    conversation: list[ConversationMessage],
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
    plan_rationale: str | None = None,
) -> ToolProcessingResult | None:
    requested_terminal_output_type = terminal_output_type_for_conversation(
        conversation,
        plan_edit_context=plan_edit_context,
        prior_plan=prior_plan_for_revision,
    )
    scoped_revision = resolve_scoped_step_revision_if_requested(
        context=plan_edit_context,
        prior_spec=(
            prior_plan_for_revision.spec if prior_plan_for_revision is not None else None
        ),
        latest_user_text=_latest_user_text(conversation),
        resource_catalog=resource_catalog,
        requested_terminal_output_type=requested_terminal_output_type,
    )
    if scoped_revision is None:
        return None
    if isinstance(scoped_revision, ScopedStepNotice):
        return ToolProcessingResult(user_message=scoped_revision.message)

    prepared = prepare_compiled_spec_for_session(
        spec=scoped_revision.spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        terminal_output_type=requested_terminal_output_type,
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
            failure_codes=frozenset(error.code for error in prepared.validation.errors)
            if prepared.validation is not None
            else frozenset(),
        )
    assert prepared.spec is not None
    assert prepared.validation is not None

    scoped_revision_feedback = validate_scoped_plan_revision(
        context=plan_edit_context,
        prior_spec=(
            prior_plan_for_revision.spec if prior_plan_for_revision is not None else None
        ),
        proposed_spec=prepared.spec,
    )
    if scoped_revision_feedback is not None:
        return ToolProcessingResult(
            feedback=format_create_intent_quality_feedback(scoped_revision_feedback),
            failure_kind="quality",
        )

    return ToolProcessingResult(
        compiled_proposal=CompiledProposal(
            content=FlowBuilderProposalContent(
                spec=prepared.spec,
                plan_rationale=plan_rationale
                or _scoped_step_revision_rationale(
                    conversation,
                    revision_kind=scoped_revision.kind,
                ),
            ),
            validation=prepared.validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(prepared.spec, catalog=resource_catalog)
                if resource_catalog is not None
                else tuple()
            ),
        )
    )


def scoped_step_revision_assistant_text(
    conversation: list[ConversationMessage],
) -> str:
    if _scoped_step_revision_uses_swedish(conversation):
        return "Jag har uppdaterat det valda steget."
    return "I updated the selected step."


def _outcome_from_processing_result(
    result: ToolProcessingResult,
) -> ScopedPlanRevisionOutcome:
    if result.user_message is not None:
        return ScopedPlanRevisionOutcome(events=(build_text_event(result.user_message),))
    if result.events:
        return ScopedPlanRevisionOutcome(events=result.events)
    return ScopedPlanRevisionOutcome(fall_through_to_active_submission=True)


def _latest_user_text(conversation: list[ConversationMessage]) -> str | None:
    for message in reversed(conversation):
        if message.role == "user" and isinstance(message.content, str):
            content = message.content.strip()
            if content:
                return content
    return None


def _scoped_step_revision_rationale(
    conversation: list[ConversationMessage],
    *,
    revision_kind: str,
) -> str:
    if revision_kind == "output_artifact":
        if _scoped_step_revision_uses_swedish(conversation):
            return "Ändrade filformatet på det valda slutsteget."
        return "Updated the selected final step output file format."
    if _scoped_step_revision_uses_swedish(conversation):
        return "Bytte modell på det valda steget."
    return "Updated the selected step model."


def _scoped_step_revision_uses_swedish(
    conversation: list[ConversationMessage],
) -> bool:
    ui_language = resolve_ui_language(conversation)
    if ui_language is not None:
        return ui_language == "sv"
    latest = (_latest_user_text(conversation) or "").casefold()
    return any(token in latest for token in ("modell", "ändra", "fil", "istället"))
