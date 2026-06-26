from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    BackendQuestionPersistenceResult,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import RuntimeToolCall
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_intent_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_events import build_plan_event
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    build_mcp_resource_selection_question,
    mcp_clarification_issue_if_needed,
    mcp_selection_policy_feedback,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    store_plan_and_update_conversation,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    format_contextual_quality_feedback,
    format_create_contextual_quality_feedback,
    format_quality_feedback,
    format_validation_feedback,
    resolve_ui_language,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
    record_proposal_first_attempt,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.flow_authoring_spec import FlowDraftSpecCore
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

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

        mcp_clarification_events = await self._mcp_clarification_events_if_needed(
            request=request,
            assistant_metadata_builder=_accepted_proposal_metadata,
        )
        if mcp_clarification_events:
            return ToolProcessingResult(
                events=mcp_clarification_events.events,
                new_planning_state_version=(
                    mcp_clarification_events.new_planning_state_version
                ),
            )

        mcp_policy_feedback = self._mcp_policy_feedback(
            request=request,
            spec=request.compiled.content.spec,
        )
        compiled = request.compiled
        if request.target_kind == TargetKind.CREATE:
            create_result = self._create_quality_result(
                request=request,
                compiled=compiled,
                mcp_policy_feedback=mcp_policy_feedback,
            )
            if create_result is not None:
                return create_result
        elif request.target_kind == TargetKind.EDIT:
            edit_result = self._edit_quality_result(
                request=request,
                compiled=compiled,
                mcp_policy_feedback=mcp_policy_feedback,
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

    async def _mcp_clarification_events_if_needed(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        assistant_metadata_builder: Callable[[], dict[str, Any] | None],
    ) -> BackendQuestionPersistenceResult | None:
        issue = mcp_clarification_issue_if_needed(
            conversation=request.conversation,
            spec=request.compiled.content.spec,
            catalog=request.resource_catalog,
            signal_text=aggregate_freeform_user_text(request.conversation),
        )
        if issue is None:
            return None
        assert request.resource_catalog is not None

        question_data, assistant_text = build_mcp_resource_selection_question(
            issue=issue,
            catalog=request.resource_catalog,
            language=resolve_ui_language(request.conversation) or "sv",
        )
        logger.info(
            "ai_builder_mcp_selection_requires_clarification "
            "session_id=%s step_ref=%s requested_mcp=%s reason=%s selected_server_refs=%s",
            request.session_id,
            issue.step_ref,
            issue.requested_name,
            issue.reason,
            sorted(issue.selected_server_refs),
        )
        return await persist_backend_question(
            repo=self.repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            question=BackendQuestion(
                question_data=question_data,
                assistant_text=assistant_text,
            ),
            assistant_metadata=assistant_metadata_builder(),
            tool_content=(
                "MCP selection question presented because MCP usage requires explicit "
                "user selection from enabled space resources."
            ),
            flow=request.flow,
        )

    def _mcp_policy_feedback(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        spec: FlowDraftSpecCore,
    ) -> str | None:
        if request.resource_catalog is None:
            return None
        feedback = mcp_selection_policy_feedback(
            conversation=request.conversation,
            spec=spec,
            catalog=request.resource_catalog,
        )
        if feedback is not None:
            logger.info(
                "ai_builder_mcp_selection_policy_violation "
                "session_id=%s tool_name=%s tool_call_id=%s",
                request.session_id,
                request.tool_name,
                request.tool_call_id,
            )
        return feedback

    def _create_quality_result(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        compiled: CompiledProposal,
        mcp_policy_feedback: str | None,
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
            contextual_hint = format_create_contextual_quality_feedback(
                conversation=request.conversation,
                spec=compiled.content.spec,
                aggregation_intent=compiled.aggregation_intent,
                resource_catalog=request.resource_catalog,
            )
            hard_feedback = format_validation_feedback(
                spec=compiled.content.spec,
                errors=compiled.validation.errors,
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
        contextual_quality_feedback = format_create_contextual_quality_feedback(
            conversation=request.conversation,
            spec=compiled.content.spec,
            aggregation_intent=compiled.aggregation_intent,
            resource_catalog=request.resource_catalog,
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
        )

    def _edit_quality_result(
        self,
        *,
        request: CompiledProposalFinalizationRequest,
        compiled: CompiledProposal,
        mcp_policy_feedback: str | None,
    ) -> ToolProcessingResult | None:
        quality_feedback = format_quality_feedback(
            compiled.validation,
            quality_retry_warning_codes=self._quality_retry_warning_codes,
        )
        contextual_quality_feedback = format_contextual_quality_feedback(
            conversation=request.conversation,
            spec=compiled.content.spec,
            flow=request.flow,
            resource_catalog=request.resource_catalog,
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
        )
