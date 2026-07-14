from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_conversation_metadata import RuntimeToolCall
from eneo.flows.ai_builder.ai_builder_create_feedback import (
    format_create_intent_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_events import build_plan_event
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_store import (
    store_plan_and_update_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    build_create_contextual_quality_feedback,
    format_contextual_quality_feedback,
    format_quality_feedback,
    format_validation_feedback,
    warnings_for_quality_retry,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
    record_proposal_first_attempt,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.ai_builder.planning_state import PlanningState
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)


@dataclass(frozen=True)
class CompiledProposalFinalizationRequest:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    tool_name: str
    target_kind: TargetKind
    arguments: dict[str, Any]
    assistant_content: str
    assistant_metadata: dict[str, Any] | None
    tool_call_id: str
    metadata_tool_call: RuntimeToolCall | None
    compiled: CompiledProposal
    resource_catalog: AIBuilderResourceCatalog | None
    flow: "Flow | None"
    request_id: str
    usage_tracker: ProposalTurnTelemetry | None
    planning_state: PlanningState | None
    requested_output_sections: RequestedOutputSections = EMPTY_REQUESTED_OUTPUT_SECTIONS

    @property
    def session_id(self) -> UUID:
        return self.turn.session_id


class CompiledProposalFinalizer:
    def __init__(
        self,
        *,
        repo: AIBuilderRepository,
        quality_retry_warning_codes: set[str] | frozenset[str],
    ) -> None:
        self.repo = repo
        self._quality_retry_warning_codes = frozenset(quality_retry_warning_codes)

    async def finalize_compiled_proposal(
        self,
        request: CompiledProposalFinalizationRequest,
    ) -> ToolProcessingResult:
        metadata_built = False
        assistant_metadata = request.assistant_metadata

        def _accepted_proposal_metadata() -> dict[str, Any] | None:
            nonlocal assistant_metadata, metadata_built
            if metadata_built:
                return assistant_metadata
            if request.metadata_tool_call is not None:
                # Record success before building metadata; telemetry reads it.
                record_proposal_first_attempt(
                    request.usage_tracker,
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    success=True,
                )
                assistant_metadata = assistant_metadata_with_usage(
                    conversation=request.conversation,
                    base_metadata=assistant_metadata,
                    usage_tracker=request.usage_tracker,
                    tool_calls=[request.metadata_tool_call],
                )
            metadata_built = True
            return assistant_metadata

        compiled = request.compiled
        if request.target_kind == TargetKind.CREATE:
            create_result = self._create_quality_result(
                request=request,
                compiled=compiled,
            )
            if create_result is not None:
                return create_result
        elif request.target_kind == TargetKind.EDIT:
            edit_result = self._edit_quality_result(
                request=request,
                compiled=compiled,
            )
            if edit_result is not None:
                return edit_result

        stored_plan = await store_plan_and_update_conversation(
            repo=self.repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            assistant_content=request.assistant_content,
            assistant_metadata=_accepted_proposal_metadata(),
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            compiled=compiled,
            flow=request.flow,
            planning_state_overlay=request.planning_state,
        )
        return ToolProcessingResult(
            events=(
                build_plan_event(
                    plan_id=stored_plan.plan.id,
                    proposal=stored_plan.proposal.content,
                ),
            ),
            new_planning_state_version=stored_plan.new_planning_state_version,
        )

    def _create_quality_result(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        compiled: CompiledProposal,
    ) -> ToolProcessingResult | None:
        if not compiled.validation.valid:
            logger.info(
                "Compiled create spec validation failed: %s",
                [error.message for error in compiled.validation.errors],
            )
            quality_hint = format_quality_feedback(
                compiled.validation,
                quality_retry_warning_codes=self._quality_retry_warning_codes,
            )
            contextual_quality = build_create_contextual_quality_feedback(
                conversation=request.conversation,
                spec=compiled.content.spec,
                aggregation_intent=compiled.aggregation_intent,
                resource_catalog=request.resource_catalog,
                planning_state=request.planning_state,
                requested_output_sections=request.requested_output_sections,
            )
            hard_feedback = format_validation_feedback(
                spec=compiled.content.spec,
                errors=compiled.validation.errors,
            )
            combined_feedback = "\n\n".join(
                feedback
                for feedback in (
                    hard_feedback,
                    quality_hint,
                    contextual_quality.feedback,
                )
                if feedback
            )
            return ToolProcessingResult(
                feedback=format_create_intent_quality_feedback(combined_feedback),
                failure_kind="validation",
                failure_codes=frozenset(
                    error.code for error in compiled.validation.errors
                ),
            )

        quality_feedback = format_quality_feedback(
            compiled.validation,
            quality_retry_warning_codes=self._quality_retry_warning_codes,
        )
        quality_failure_codes = frozenset(
            warning.code
            for warning in warnings_for_quality_retry(
                compiled.validation,
                retry_warning_codes=self._quality_retry_warning_codes,
            )
        )
        contextual_quality = build_create_contextual_quality_feedback(
            conversation=request.conversation,
            spec=compiled.content.spec,
            aggregation_intent=compiled.aggregation_intent,
            resource_catalog=request.resource_catalog,
            planning_state=request.planning_state,
            requested_output_sections=request.requested_output_sections,
        )
        quality_failure_codes = quality_failure_codes | contextual_quality.failure_codes
        combined_quality_feedback = (
            "\n\n".join(
                feedback
                for feedback in (
                    quality_feedback,
                    contextual_quality.feedback,
                )
                if feedback is not None
            )
            or None
        )
        combined_quality_feedback = format_create_intent_quality_feedback(
            combined_quality_feedback
        )
        if combined_quality_feedback is None:
            return None
        logger.info(
            "ai_builder_create_quality_feedback "
            "session_id=%s tool_call_id=%s warning_codes=%s feedback=%s",
            request.session_id,
            request.tool_call_id,
            ",".join(warning.code for warning in compiled.validation.warnings) or "-",
            combined_quality_feedback[:1200],
        )
        return ToolProcessingResult(
            feedback=combined_quality_feedback,
            failure_kind="quality",
            failure_codes=quality_failure_codes,
        )

    def _edit_quality_result(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        compiled: CompiledProposal,
    ) -> ToolProcessingResult | None:
        quality_feedback = format_quality_feedback(
            compiled.validation,
            quality_retry_warning_codes=self._quality_retry_warning_codes,
        )
        quality_failure_codes = frozenset(
            warning.code
            for warning in warnings_for_quality_retry(
                compiled.validation,
                retry_warning_codes=self._quality_retry_warning_codes,
            )
        )
        contextual_quality_feedback = format_contextual_quality_feedback(
            conversation=request.conversation,
            spec=compiled.content.spec,
            flow=request.flow,
            resource_catalog=request.resource_catalog,
            planning_state=request.planning_state,
            requested_output_sections=request.requested_output_sections,
        )
        combined_quality_feedback = "\n\n".join(
            feedback
            for feedback in (
                quality_feedback,
                contextual_quality_feedback,
            )
            if feedback
        )
        if not combined_quality_feedback:
            return None
        logger.info(
            "ai_builder_edit_quality_feedback "
            "session_id=%s warning_codes=%s feedback=%s",
            request.session_id,
            ",".join(warning.code for warning in compiled.validation.warnings) or "-",
            combined_quality_feedback[:1200],
        )
        return ToolProcessingResult(
            feedback=combined_quality_feedback,
            failure_kind="quality",
            failure_codes=quality_failure_codes,
        )
