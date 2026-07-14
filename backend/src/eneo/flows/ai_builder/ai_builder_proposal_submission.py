"""Own active create/edit proposal submission behavior."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    build_proposal_architecture_error_event,
    record_proposal_architecture_failure,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    PROPOSE_FLOW_CREATE_FORCED_TOOL_PROMPT,
    process_create_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_proposal import (
    PROPOSE_FLOW_EDIT_FORCED_TOOL_PROMPT,
    process_edit_arguments,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderProviderOutcomeUnknownException,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import build_text_event
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionMessage,
    LLMCompletionToolCall,
    call_proposal_completion,
    make_usage_tracked_proposal_completion,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_retry import (
    ForcedToolAfterTextRequest,
    ProposalSelfCorrectionRequest,
    build_proposal_self_correction_request,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalAttemptFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    log_proposal_failed_turn,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
    record_proposal_first_attempt,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    LLMMessageParam,
    ProposalTurnContext,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    PROPOSE_FLOW_TOOL_NAME,
    build_propose_flow_tool_schema,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)


@dataclass(frozen=True)
class ForcedSubmissionResponse:
    text_content: str | None
    tool_call: LLMCompletionToolCall


def _forced_submission_response(
    *,
    message: LLMCompletionMessage,
) -> ForcedSubmissionResponse | None:
    tool_calls = message.tool_calls
    if len(tool_calls) != 1:
        return None

    tool_call = tool_calls[0]
    if tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
        return None

    return ForcedSubmissionResponse(
        text_content=message.content,
        tool_call=tool_call,
    )


class ProposalSubmissionOwner:
    """Own active create/edit proposal submission for AI Builder turns."""

    def __init__(
        self,
        *,
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        self_correction_bumped_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: frozenset[str],
        compiled_proposal_finalizer: CompiledProposalFinalizer | None = None,
    ) -> None:
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self._compiled_proposal_finalizer = (
            compiled_proposal_finalizer
            or CompiledProposalFinalizer(
                repo=repo,
                quality_retry_warning_codes=quality_retry_warning_codes,
            )
        )

    def _active_submission_tool_schemas(
        self,
        *,
        flow: "Flow | None",
        resource_catalog: AIBuilderResourceCatalog,
    ) -> list[dict[str, Any]]:
        return [
            build_propose_flow_tool_schema(
                current_steps=None if flow is None else list(flow.steps),
                resource_catalog=resource_catalog,
            )
        ]

    def dispatch_submission_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: RuntimeToolCall,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None] | None:
        tool_name = tool_call.function.name
        if tool_name != PROPOSE_FLOW_TOOL_NAME:
            return None
        return self._handle_propose_flow_tool_call(ctx=ctx, tool_call=tool_call)

    def contains_submission_tool_call(
        self,
        tool_calls: Sequence[RuntimeToolCall],
    ) -> bool:
        return any(call.function.name == PROPOSE_FLOW_TOOL_NAME for call in tool_calls)

    async def run_active_submission_attempt(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        llm_messages: list[LLMMessageParam],
        completion_model_route: ResolvedCompletionModelRoute,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog,
        max_output_tokens: int,
        proposal_temperature: float,
        request_id: str,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        assistant_metadata: dict[str, Any] | None = None,
        planning_state: PlanningState | None = None,
        requested_output_sections: RequestedOutputSections = (
            EMPTY_REQUESTED_OUTPUT_SECTIONS
        ),
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
        before_provider_call: Callable[[], Awaitable[None]] | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        target_kind = TargetKind.EDIT if flow is not None else TargetKind.CREATE
        tool_schemas = self._active_submission_tool_schemas(
            flow=flow,
            resource_catalog=resource_catalog,
        )
        usage_tracker = ProposalTurnTelemetry(
            request_id=request_id,
            model=completion_model_route.litellm_model,
            target_kind=target_kind,
        )
        ctx = ProposalTurnContext(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            tool_schemas=tool_schemas,
            route=completion_model_route,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            requested_output_sections=requested_output_sections,
            usage_tracker=usage_tracker,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            before_provider_call=before_provider_call,
        )
        if not ctx.proposal_call_budget.try_start_call():
            raise RuntimeError("Fresh proposal turn exhausted its provider call budget")
        usage_tracker.start_attempt(counts_as_repair=False)
        try:
            response = await call_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=usage_tracker,
                request=ctx.completion_request(
                    temperature=proposal_temperature,
                    tool_choice=forced_tool_choice(PROPOSE_FLOW_TOOL_NAME),
                ),
                before_provider_call=before_provider_call,
            )
        except (AIBuilderBadRequestException, AIBuilderProviderOutcomeUnknownException):
            raise
        except Exception as error:
            usage_tracker.record_attempt_failure(failure_kind="provider_error")
            logger.error("AI Builder proposal task failed", exc_info=error)
            log_proposal_failed_turn(
                usage_tracker=usage_tracker,
                session_id=turn.session_id,
                branch="provider_completion_error",
                final_failure_kind="provider_error",
                final_error_code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR.value,
            )
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.PLANNER,
                request_id=request_id,
            )
            return

        if not response.choices:
            usage_tracker.record_attempt_failure(failure_kind="missing_submission_tool")
            log_proposal_failed_turn(
                usage_tracker=usage_tracker,
                session_id=turn.session_id,
                branch="empty_completion_choices",
                final_failure_kind="missing_submission_tool",
                final_error_code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING.value,
            )
            yield build_ai_builder_error_event(
                message=(
                    "The AI planner did not return a valid flow proposal. "
                    "Please try again or use a more capable model."
                ),
                code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING,
                phase=AIBuilderErrorPhase.PROPOSAL,
                request_id=request_id,
            )
            return

        choice = response.choices[0]
        if choice.finish_reason == "length":
            usage_tracker.record_attempt_failure(failure_kind="provider_truncation")
            log_proposal_failed_turn(
                usage_tracker=usage_tracker,
                session_id=turn.session_id,
                branch="provider_truncation",
                final_failure_kind="provider_truncation",
                final_error_code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG.value,
            )
            yield build_ai_builder_error_event(
                message=(
                    "The AI planner output was cut off before it returned a complete "
                    "flow proposal. Try again with a shorter request or a model with "
                    "a larger output limit."
                ),
                code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG,
                phase=AIBuilderErrorPhase.PROPOSAL,
                request_id=request_id,
            )
            return

        message = choice.message
        forced_response = _forced_submission_response(
            message=message,
        )
        if forced_response is not None:
            dispatch = self.dispatch_submission_tool_call(
                ctx=replace(ctx, text_content=forced_response.text_content),
                tool_call=forced_response.tool_call,
            )
            if dispatch is not None:
                yielded = False
                async for event in dispatch:
                    yielded = True
                    yield event
                if yielded:
                    return

        forced_events = await self._retry_forced_proposal_after_text(
            ctx=ctx,
            correction_messages=llm_messages,
            assistant_text=message.content or "",
        )
        if forced_events is not None:
            for event in forced_events:
                yield event
            return

        log_proposal_failed_turn(
            usage_tracker=usage_tracker,
            session_id=turn.session_id,
            branch="forced_tool_retry_missing_submission",
            final_failure_kind="missing_submission_tool",
            final_error_code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING.value,
        )
        yield build_ai_builder_error_event(
            message=(
                "The AI planner did not return a valid flow proposal. "
                "Please try again or use a more capable model."
            ),
            code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING,
            phase=AIBuilderErrorPhase.PROPOSAL,
            request_id=request_id,
        )

    def _proposal_retry_config(
        self,
        *,
        target_kind: TargetKind,
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        request_id: str,
        planning_state: PlanningState | None,
        plan_edit_context: AIBuilderPlanEditContext | None,
        prior_plan_for_revision: BuilderPlan | None,
        usage_tracker: ProposalTurnTelemetry | None,
        requested_output_sections: RequestedOutputSections,
    ) -> ToolRetryConfig:
        async def _process_tool_invocation(
            invocation: ToolRetryInvocation,
        ) -> ToolProcessingResult:
            return await self._process_submission_invocation(
                invocation=invocation,
                target_kind=target_kind,
                planning_state=planning_state,
                assistant_snapshots=assistant_snapshots,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
                request_id=request_id,
                usage_tracker=usage_tracker,
                requested_output_sections=requested_output_sections,
            )

        return ToolRetryConfig(
            target_kind=target_kind,
            forced_tool_prompt=(
                PROPOSE_FLOW_CREATE_FORCED_TOOL_PROMPT
                if target_kind == TargetKind.CREATE
                else PROPOSE_FLOW_EDIT_FORCED_TOOL_PROMPT
            ),
            process_tool_invocation=_process_tool_invocation,
        )

    async def _process_submission_invocation(
        self,
        *,
        invocation: ToolRetryInvocation,
        target_kind: TargetKind,
        planning_state: PlanningState | None,
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        plan_edit_context: AIBuilderPlanEditContext | None,
        prior_plan_for_revision: BuilderPlan | None,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry | None,
        requested_output_sections: RequestedOutputSections,
        metadata_tool_call: RuntimeToolCall | None = None,
    ) -> ToolProcessingResult:
        if target_kind == TargetKind.CREATE:
            result = await process_create_intent_arguments(
                turn=invocation.turn,
                conversation=invocation.conversation,
                arguments=invocation.arguments,
                tool_call_id=invocation.tool_call_id,
                available_model_refs=invocation.available_model_refs,
                available_kb_refs=invocation.available_kb_refs,
                resource_catalog=invocation.resource_catalog,
                planning_state=planning_state,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
            )
        else:
            result = await process_edit_arguments(
                turn=invocation.turn,
                conversation=invocation.conversation,
                arguments=invocation.arguments,
                available_model_refs=invocation.available_model_refs,
                available_kb_refs=invocation.available_kb_refs,
                flow=invocation.flow,
                assistant_snapshots=assistant_snapshots,
                resource_catalog=invocation.resource_catalog,
                planning_state=planning_state,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
            )
        if result.compiled_proposal is None:
            return result
        return await self._finalize_invocation_proposal(
            invocation=invocation,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=target_kind,
            compiled=result.compiled_proposal,
            request_id=request_id,
            usage_tracker=usage_tracker,
            metadata_tool_call=metadata_tool_call,
            planning_state=planning_state,
            requested_output_sections=requested_output_sections,
        )

    async def _finalize_invocation_proposal(
        self,
        *,
        invocation: ToolRetryInvocation,
        tool_name: str,
        target_kind: TargetKind,
        compiled: CompiledProposal,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry | None,
        metadata_tool_call: RuntimeToolCall | None,
        planning_state: PlanningState | None,
        requested_output_sections: RequestedOutputSections,
    ) -> ToolProcessingResult:
        return await self._compiled_proposal_finalizer.finalize_compiled_proposal(
            CompiledProposalFinalizationRequest(
                turn=invocation.turn,
                conversation=invocation.conversation,
                new_messages_start=invocation.new_messages_start,
                tool_name=tool_name,
                target_kind=target_kind,
                arguments=invocation.arguments,
                assistant_content=invocation.assistant_content,
                assistant_metadata=invocation.assistant_metadata,
                tool_call_id=invocation.tool_call_id,
                metadata_tool_call=metadata_tool_call,
                compiled=compiled,
                resource_catalog=invocation.resource_catalog,
                flow=invocation.flow,
                request_id=request_id,
                usage_tracker=usage_tracker,
                planning_state=planning_state,
                requested_output_sections=requested_output_sections,
            )
        )

    def _build_self_correction_request(
        self,
        *,
        ctx: ProposalTurnContext,
        error_message: str,
        tool_call: RuntimeToolCall,
        retry_config: ToolRetryConfig,
        reason: ProposalRepairReason,
        failure_codes: frozenset[str] = frozenset(),
    ) -> ProposalSelfCorrectionRequest:
        return build_proposal_self_correction_request(
            ctx=ctx,
            error_message=error_message,
            tool_call=tool_call,
            retry_config=retry_config,
            failure_codes=failure_codes,
            initial_failure_kind=_repair_failure_kind(reason),
            self_correction_temperature=self.self_correction_temperature,
            self_correction_bumped_temperature=self.self_correction_bumped_temperature,
            forced_proposal_temperature=self.forced_proposal_temperature,
            repair_completion=make_usage_tracked_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=ctx.usage_tracker,
                before_provider_call=ctx.before_provider_call,
            ),
        )

    def _record_failed_proposal_attempt_repair(
        self,
        *,
        usage_tracker: ProposalTurnTelemetry | None,
        request_id: str,
        reason: ProposalRepairReason,
        failure_codes: frozenset[str] = frozenset(),
    ) -> None:
        if usage_tracker is not None:
            usage_tracker.record_attempt_failure(
                failure_kind=_attempt_failure_kind(reason),
                failure_codes=failure_codes,
            )
        record_proposal_first_attempt(
            usage_tracker,
            request_id=request_id,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            success=False,
            failure_kind=reason,
        )
        _record_proposal_repair_invocation(
            usage_tracker,
            request_id=request_id,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            reason=reason,
        )

    async def _run_proposal_self_correction(
        self,
        *,
        ctx: ProposalTurnContext,
        error_message: str,
        tool_call: RuntimeToolCall,
        retry_config: ToolRetryConfig,
        reason: ProposalRepairReason,
        failure_codes: frozenset[str] = frozenset(),
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        self._record_failed_proposal_attempt_repair(
            usage_tracker=ctx.usage_tracker,
            request_id=ctx.request_id,
            reason=reason,
            failure_codes=failure_codes,
        )
        async for event in run_tool_self_correction(
            self._build_self_correction_request(
                ctx=ctx,
                error_message=error_message,
                tool_call=tool_call,
                retry_config=retry_config,
                reason=reason,
                failure_codes=failure_codes,
            )
        ):
            yield event

    async def _handle_propose_flow_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: RuntimeToolCall,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        target_kind = TargetKind.CREATE if ctx.flow is None else TargetKind.EDIT
        is_create = target_kind == TargetKind.CREATE
        assistant_snapshots = None if is_create else ctx.assistant_snapshots
        planning_state = ctx.planning_state

        retry_config = self._proposal_retry_config(
            target_kind=target_kind,
            assistant_snapshots=assistant_snapshots,
            request_id=ctx.request_id,
            planning_state=planning_state,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
            usage_tracker=ctx.usage_tracker,
            requested_output_sections=ctx.requested_output_sections,
        )

        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError as error:
            async for event in self._run_proposal_self_correction(
                ctx=ctx,
                error_message=f"Invalid propose_flow arguments: {error}",
                tool_call=tool_call,
                retry_config=retry_config,
                reason="parse",
                failure_codes=frozenset(),
            ):
                yield event
            return

        assistant_content = (
            "Här är mitt förslag:" if is_create else ctx.text_content or ""
        )
        try:
            result = await self._process_submission_invocation(
                invocation=_initial_submission_invocation(
                    ctx=ctx,
                    arguments=arguments,
                    assistant_content=assistant_content,
                    tool_call=tool_call,
                ),
                target_kind=target_kind,
                planning_state=planning_state,
                assistant_snapshots=assistant_snapshots,
                plan_edit_context=ctx.plan_edit_context,
                prior_plan_for_revision=ctx.prior_plan_for_revision,
                request_id=ctx.request_id,
                usage_tracker=ctx.usage_tracker,
                requested_output_sections=ctx.requested_output_sections,
                metadata_tool_call=tool_call,
            )
            if is_create and result.user_message is not None:
                yield build_text_event(result.user_message)
                return
            if not result.events:
                proposal_repair_reason = proposal_repair_reason_from_tool_failure(
                    result.failure_kind
                )
                fallback_feedback = (
                    "Invalid propose_flow draft."
                    if is_create
                    else "Invalid propose_flow arguments."
                )
                async for event in self._run_proposal_self_correction(
                    ctx=ctx,
                    error_message=result.feedback or fallback_feedback,
                    tool_call=tool_call,
                    retry_config=retry_config,
                    reason=proposal_repair_reason,
                    failure_codes=result.failure_codes,
                ):
                    yield event
                return

            for event in result.events:
                yield event
        except AIBuilderProviderOutcomeUnknownException:
            raise
        except AIBuilderArchitectureError as error:
            if not is_create:
                raise
            # Create proposal architecture failures are user-visible proposal
            # errors; edit keeps propagating the same exception by design.
            record_proposal_architecture_failure(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=PROPOSE_FLOW_TOOL_NAME,
            )
            yield build_proposal_architecture_error_event(
                error,
                request_id=ctx.request_id,
                tool_name=PROPOSE_FLOW_TOOL_NAME,
            )
            return
        except Exception as error:
            # A proposal response already came back from the provider. If local
            # compilation or persistence now fails, replay could repeat paid
            # provider work, so the durable turn must remain outcome-unknown.
            raise AIBuilderProviderOutcomeUnknownException() from error

    async def _retry_forced_proposal_after_text(
        self,
        *,
        ctx: ProposalTurnContext,
        correction_messages: list[LLMMessageParam],
        assistant_text: str,
    ) -> tuple[AIBuilderStreamEvent, ...] | None:
        self._record_failed_proposal_attempt_repair(
            usage_tracker=ctx.usage_tracker,
            request_id=ctx.request_id,
            reason="missing_submission_tool",
        )
        retry_config = self._proposal_retry_config(
            target_kind=TargetKind.CREATE if ctx.flow is None else TargetKind.EDIT,
            assistant_snapshots=ctx.assistant_snapshots,
            request_id=ctx.request_id,
            planning_state=ctx.planning_state,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
            usage_tracker=ctx.usage_tracker,
            requested_output_sections=ctx.requested_output_sections,
        )
        outcome = await run_forced_tool_retry_after_text(
            ForcedToolAfterTextRequest(
                ctx=ctx,
                correction_messages=correction_messages,
                assistant_text=assistant_text,
                retry_config=retry_config,
                forced_proposal_temperature=self.forced_proposal_temperature,
                repair_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=ctx.usage_tracker,
                    before_provider_call=ctx.before_provider_call,
                ),
                truncation_error_phase=AIBuilderErrorPhase.PROPOSAL,
            )
        )
        return outcome.events


def _initial_submission_invocation(
    *,
    ctx: ProposalTurnContext,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call: RuntimeToolCall,
) -> ToolRetryInvocation:
    return ToolRetryInvocation(
        turn=ctx.turn,
        conversation=ctx.conversation,
        new_messages_start=ctx.new_messages_start,
        arguments=arguments,
        assistant_content=assistant_content,
        tool_call_id=tool_call.id,
        available_model_refs=ctx.available_model_refs,
        available_kb_refs=ctx.available_kb_refs,
        resource_catalog=ctx.resource_catalog,
        flow=ctx.flow,
        assistant_metadata=ctx.assistant_metadata,
    )


def _record_proposal_repair_invocation(
    usage_tracker: ProposalTurnTelemetry | None,
    *,
    request_id: str,
    tool_name: str,
    reason: ProposalRepairReason,
) -> None:
    if usage_tracker is None:
        return
    usage_tracker.record_repair_invocation(reason=reason)
    log_proposal_repair_invoked(
        request_id=request_id,
        tool_name=tool_name,
        reason=reason,
    )


def _repair_failure_kind(
    reason: ProposalRepairReason,
) -> ToolProcessingFailureKind:
    if reason == "parse":
        return "parse"
    if reason == "quality":
        return "quality"
    return "validation"


def _attempt_failure_kind(
    reason: ProposalRepairReason,
) -> ProposalAttemptFailureKind:
    return reason
