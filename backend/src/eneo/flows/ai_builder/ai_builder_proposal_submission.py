"""Own active create/edit proposal submission behavior."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    architecture_failure_outcome,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
    make_provider_safe_server_tool_call_id,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    PROPOSE_FLOW_CREATE_FORCED_TOOL_PROMPT,
    process_create_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
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
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
)
from eneo.flows.ai_builder.ai_builder_events import build_status_event
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionMessage,
    LLMCompletionToolCall,
    call_proposal_completion,
    make_usage_tracked_proposal_completion,
)
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    decline_message,
    decline_reason_from_arguments,
    persist_non_plan_turn,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    capture_malformed_proposal_arguments,
    capture_rejected_proposal_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_proposal_retry import (
    ForcedToolAfterTextRequest,
    ForcedToolContinuation,
    ForcedToolRepair,
    ProposalSelfCorrectionRequest,
    build_proposal_self_correction_request,
    log_terminal_failure,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
    terminal_failure_event,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_JSON_FAILURE_CODE,
    PROPOSAL_PARSE_SCHEMA_FAILURE_CODE,
    ProposalAttemptFailureKind,
    ProposalFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    log_proposal_failed_turn,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
    record_proposal_first_attempt,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    CorrectableFailure,
    ProposalAnswer,
    ProposalCallBudgetExhausted,
    ProposalCompleted,
    ProposalMessageGroup,
    ProposalReady,
    ProposalTurnContext,
    SubmissionOutcome,
    TerminalFailure,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderRequestBudget
from eneo.flows.ai_builder.ai_builder_tool_names import (
    DECLINE_FLOW_CHANGE_TOOL_NAME,
)
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    PROPOSE_FLOW_TOOL_NAME,
    AdmissionNormalizerFamily,
    ProposalToolArgumentsError,
    ProposalToolSchema,
    admit_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.planning_state import (
    PlanningState,
    PlanningStatePayloadTooLargeError,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.ai_builder.ai_builder_create_compile_context import (
        CreateCompileContext,
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
    if tool_call.function.name not in _SUBMISSION_TOOL_NAMES:
        return None

    return ForcedSubmissionResponse(
        text_content=message.content,
        tool_call=tool_call,
    )


_SUBMISSION_TOOL_NAMES = frozenset(
    {PROPOSE_FLOW_TOOL_NAME, DECLINE_FLOW_CHANGE_TOOL_NAME}
)


class ProposalSubmissionOwner:
    """Own active create/edit proposal submission for AI Builder turns."""

    def __init__(
        self,
        *,
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: frozenset[str],
        compiled_proposal_finalizer: CompiledProposalFinalizer | None = None,
    ) -> None:
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self._compiled_proposal_finalizer = (
            compiled_proposal_finalizer
            or CompiledProposalFinalizer(
                repo=repo,
                quality_retry_warning_codes=quality_retry_warning_codes,
            )
        )

    def dispatch_submission_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: RuntimeToolCall,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None] | None:
        tool_name = tool_call.function.name
        if tool_name == DECLINE_FLOW_CHANGE_TOOL_NAME:
            return self._handle_decline_flow_change_tool_call(
                ctx=ctx, tool_call=tool_call
            )
        if tool_name != PROPOSE_FLOW_TOOL_NAME:
            return None
        return self._handle_propose_flow_tool_call(ctx=ctx, tool_call=tool_call)

    async def run_active_submission_attempt(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        message_groups: tuple[ProposalMessageGroup, ...],
        completion_model_route: ResolvedCompletionModelRoute,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog,
        proposal_tool_schema: ProposalToolSchema,
        decline_tool_schema: ProposalToolSchema | None = None,
        proposal_temperature: float,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        assistant_metadata: dict[str, Any] | None = None,
        planning_state: PlanningState,
        compile_context: "CreateCompileContext | None",
        obligation_projection: ProposalObligationProjection | None = None,
        plan_edit_context: ResolvedAIBuilderEditContext | None = None,
        prior_spec_for_revision: FlowDraftSpecCore | None = None,
        before_provider_call: Callable[[], Awaitable[None]] | None = None,
        proposal_request_budget: AIBuilderRequestBudget,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        ctx = ProposalTurnContext(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            message_groups=message_groups,
            proposal_tool_schema=proposal_tool_schema,
            decline_tool_schema=decline_tool_schema,
            route=completion_model_route,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            obligation_projection=obligation_projection,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            compile_context=compile_context,
            usage_tracker=usage_tracker,
            plan_edit_context=plan_edit_context,
            prior_spec_for_revision=prior_spec_for_revision,
            before_provider_call=before_provider_call,
            proposal_request_budget=proposal_request_budget,
        )
        # Said before the provider is asked, so the client learns what is
        # happening while it happens; the planner forwards statuses at once.
        yield build_status_event(AIBuilderStatus.DRAFTING_FLOW)
        try:
            response = await call_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=usage_tracker,
                call_kind="proposal_initial",
                request=ctx.completion_request(
                    temperature=proposal_temperature,
                ),
                before_provider_call=before_provider_call,
            )
        except ProposalCallBudgetExhausted as error:
            raise RuntimeError(
                "Fresh proposal turn exhausted its provider call budget"
            ) from error
        except AIBuilderBadRequestException:
            raise
        except Exception as error:
            usage_tracker.finalize_pending_attempt()
            logger.error(
                "AI Builder proposal completion processing failed", exc_info=error
            )
            log_proposal_failed_turn(
                usage_tracker=usage_tracker,
                session_id=turn.session_id,
                branch="internal_submission_error",
                final_failure_kind="internal_error",
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

        yield build_status_event(AIBuilderStatus.CHECKING_FLOW)
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

        continuation, retry_config = await self._retry_forced_proposal_after_text(
            ctx=ctx,
            correction_message_groups=message_groups,
            assistant_text=message.content or "",
        )
        if isinstance(continuation, ProposalCompleted):
            for event in continuation.events:
                yield event
            return
        if isinstance(continuation, ForcedToolRepair):
            async for event in self._run_proposal_self_correction(
                ctx=ctx,
                failure=continuation.failure,
                tool_call=continuation.tool_call,
                retry_config=retry_config,
            ):
                yield event
            return
        log_terminal_failure(ctx, continuation, forced=True)
        yield terminal_failure_event(continuation, request_id=request_id)

    def _proposal_retry_config(
        self,
        *,
        target_kind: TargetKind,
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        request_id: str,
        planning_state: PlanningState,
        plan_edit_context: ResolvedAIBuilderEditContext | None,
        prior_spec_for_revision: FlowDraftSpecCore | None,
        usage_tracker: ProposalTurnTelemetry | None,
        proposal_tool_schema: ProposalToolSchema,
        compile_context: "CreateCompileContext | None",
        obligation_projection: "ProposalObligationProjection | None" = None,
    ) -> ToolRetryConfig:
        async def _process_tool_invocation(
            invocation: ToolRetryInvocation,
        ) -> SubmissionOutcome:
            return await self._process_submission_invocation(
                invocation=invocation,
                target_kind=target_kind,
                planning_state=planning_state,
                assistant_snapshots=assistant_snapshots,
                plan_edit_context=plan_edit_context,
                prior_spec_for_revision=prior_spec_for_revision,
                request_id=request_id,
                usage_tracker=usage_tracker,
                proposal_tool_schema=proposal_tool_schema,
                obligation_projection=obligation_projection,
                compile_context=compile_context,
            )

        return ToolRetryConfig(
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
        planning_state: PlanningState,
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        plan_edit_context: ResolvedAIBuilderEditContext | None,
        prior_spec_for_revision: FlowDraftSpecCore | None,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry | None,
        proposal_tool_schema: ProposalToolSchema,
        compile_context: "CreateCompileContext | None",
        obligation_projection: "ProposalObligationProjection | None" = None,
        metadata_tool_call: RuntimeToolCall | None = None,
    ) -> SubmissionOutcome:
        def record_admission_normalizer_hit(
            family: AdmissionNormalizerFamily,
        ) -> None:
            if usage_tracker is not None:
                usage_tracker.record_admission_normalization_hit(family)
            logger.info(
                "ai_builder_proposal_arguments_normalized session_id=%s family=%s",
                invocation.turn.session_id,
                family,
            )

        try:
            admitted_arguments = admit_propose_flow_tool_arguments(
                arguments=invocation.arguments,
                tool_schema=proposal_tool_schema,
                on_normalizer_hit=record_admission_normalizer_hit,
            )
        except ProposalToolArgumentsError as error:
            logger.info(
                "ai_builder_proposal_schema_rejected session_id=%s validator=%s",
                invocation.turn.session_id,
                error.validator,
            )
            capture_rejected_proposal_arguments(
                invocation.arguments,
                session_id=str(invocation.turn.session_id),
                issues=[str(error)],
            )
            return CorrectableFailure(
                feedback=f"Invalid propose_flow arguments: {error}",
                kind="parse",
                codes=frozenset({PROPOSAL_PARSE_SCHEMA_FAILURE_CODE}),
            )
        if admitted_arguments is not invocation.arguments:
            invocation = replace(invocation, arguments=admitted_arguments)
        if target_kind == TargetKind.CREATE:
            if planning_state.architecture_commit is None:
                return architecture_failure_outcome(
                    AIBuilderArchitectureError(
                        public_code="architecture_materialization_failed",
                        repair_disposition="server_defect",
                        detail="Create proposal requires a committed architecture.",
                        log_context={
                            "failure_code": "architecture_commit_missing",
                            "reason": "architecture_commit_missing",
                        },
                    )
                )
            result = await process_create_intent_arguments(
                turn=invocation.turn,
                conversation=invocation.conversation,
                arguments=invocation.arguments,
                tool_call_id=invocation.tool_call_id,
                available_model_refs=invocation.available_model_refs,
                available_kb_refs=invocation.available_kb_refs,
                resource_catalog=invocation.resource_catalog,
                plan_edit_context=plan_edit_context,
                prior_spec_for_revision=prior_spec_for_revision,
                compile_context=compile_context,
                obligation_projection=obligation_projection,
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
                prior_spec_for_revision=prior_spec_for_revision,
                compile_context=compile_context,
            )
        if isinstance(result, ProposalAnswer):
            return await self._persist_invocation_answer(
                invocation=invocation,
                answer=result.answer,
                usage_tracker=usage_tracker,
                planning_state=planning_state,
            )
        if not isinstance(result, ProposalReady):
            return result
        return await self._finalize_invocation_proposal(
            invocation=invocation,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=target_kind,
            compiled=result.compiled,
            request_id=request_id,
            usage_tracker=usage_tracker,
            metadata_tool_call=metadata_tool_call,
            planning_state=planning_state,
            compile_context=compile_context,
        )

    async def _persist_invocation_answer(
        self,
        *,
        invocation: ToolRetryInvocation,
        answer: str,
        usage_tracker: ProposalTurnTelemetry | None,
        planning_state: PlanningState,
    ) -> ProposalCompleted:
        """Commit a turn that answers the user instead of proposing a plan.

        Both the first attempt and every repair reach this seam, so an answer
        is stored the same way wherever it is decided, with the arguments the
        provider actually sent.
        """

        answered = await persist_non_plan_turn(
            repo=self.repo,
            turn=invocation.turn,
            conversation=invocation.conversation,
            new_messages_start=invocation.new_messages_start,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments=invocation.arguments,
            tool_content="No plan was proposed; the user was answered.",
            message=answer,
            tool_call_id=invocation.tool_call_id,
            base_assistant_metadata=invocation.assistant_metadata,
            usage_tracker=usage_tracker,
            planning_state=planning_state,
            flow=invocation.flow,
        )
        return ProposalCompleted(events=answered)

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
        planning_state: PlanningState,
        compile_context: "CreateCompileContext | None",
    ) -> SubmissionOutcome:
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
                compile_context=compile_context,
            )
        )

    def _build_self_correction_request(
        self,
        *,
        ctx: ProposalTurnContext,
        failure: CorrectableFailure,
        tool_call: RuntimeToolCall,
        retry_config: ToolRetryConfig,
    ) -> ProposalSelfCorrectionRequest:
        return build_proposal_self_correction_request(
            ctx=ctx,
            failure=failure,
            tool_call=tool_call,
            retry_config=retry_config,
            self_correction_temperature=self.self_correction_temperature,
            forced_proposal_temperature=self.forced_proposal_temperature,
            repair_completion=make_usage_tracked_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=ctx.usage_tracker,
                call_kind="proposal_repair",
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
        failure: CorrectableFailure,
        tool_call: RuntimeToolCall,
        retry_config: ToolRetryConfig,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        self._record_failed_proposal_attempt_repair(
            usage_tracker=ctx.usage_tracker,
            request_id=ctx.request_id,
            reason=proposal_repair_reason_from_tool_failure(failure.kind),
            failure_codes=failure.codes,
        )
        async for event in run_tool_self_correction(
            self._build_self_correction_request(
                ctx=ctx,
                failure=failure,
                tool_call=tool_call,
                retry_config=retry_config,
            )
        ):
            yield event

    async def _handle_decline_flow_change_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: RuntimeToolCall,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        """Answer a request this edit contract cannot carry out.

        A declined turn is a completed turn: the model asked for it explicitly,
        so there is nothing to repair and no plan to supersede.
        """

        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError:
            arguments = {}
        reason = decline_reason_from_arguments(arguments)
        if reason is None or ctx.decline_tool_schema is None:
            # The tool was not on offer, or the reason is outside the contract.
            # Fall back to the ordinary missing-proposal handling.
            return
        record_proposal_first_attempt(
            ctx.usage_tracker,
            request_id=ctx.request_id,
            tool_name=DECLINE_FLOW_CHANGE_TOOL_NAME,
            success=True,
        )
        events = await persist_non_plan_turn(
            repo=self.repo,
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            tool_name=DECLINE_FLOW_CHANGE_TOOL_NAME,
            arguments={"reason": reason},
            tool_content="Flow change declined; no plan was proposed.",
            message=decline_message(
                reason,
                ui_language=(
                    ctx.compile_context.ui_language
                    if ctx.compile_context is not None
                    else None
                ),
            ),
            tool_call_id=make_provider_safe_server_tool_call_id(
                kind="decline_flow_change",
                stable_key=ctx.request_id,
            ),
            base_assistant_metadata=ctx.assistant_metadata,
            usage_tracker=ctx.usage_tracker,
            planning_state=ctx.planning_state,
            flow=ctx.flow,
        )
        for event in events:
            yield event

    async def _handle_propose_flow_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: RuntimeToolCall,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        target_kind = ctx.target_kind
        is_create = target_kind == TargetKind.CREATE
        assistant_snapshots = None if is_create else ctx.assistant_snapshots
        planning_state = ctx.planning_state

        retry_config = self._proposal_retry_config(
            target_kind=target_kind,
            assistant_snapshots=assistant_snapshots,
            request_id=ctx.request_id,
            planning_state=planning_state,
            plan_edit_context=ctx.plan_edit_context,
            prior_spec_for_revision=ctx.prior_spec_for_revision,
            usage_tracker=ctx.usage_tracker,
            proposal_tool_schema=ctx.proposal_tool_schema,
            obligation_projection=ctx.obligation_projection,
            compile_context=ctx.compile_context,
        )

        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError as error:
            capture_malformed_proposal_arguments(
                tool_call.function.arguments,
                session_id=str(ctx.session_id),
                error_message=str(error),
            )
            async for event in self._run_proposal_self_correction(
                ctx=ctx,
                failure=CorrectableFailure(
                    feedback=f"Invalid propose_flow arguments: {error}",
                    kind="parse",
                    codes=frozenset({PROPOSAL_PARSE_JSON_FAILURE_CODE}),
                ),
                tool_call=tool_call,
                retry_config=retry_config,
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
                prior_spec_for_revision=ctx.prior_spec_for_revision,
                request_id=ctx.request_id,
                usage_tracker=ctx.usage_tracker,
                proposal_tool_schema=ctx.proposal_tool_schema,
                obligation_projection=ctx.obligation_projection,
                compile_context=ctx.compile_context,
                metadata_tool_call=tool_call,
            )
            if isinstance(result, CorrectableFailure):
                async for event in self._run_proposal_self_correction(
                    ctx=ctx,
                    failure=result,
                    tool_call=tool_call,
                    retry_config=retry_config,
                ):
                    yield event
                return
            if isinstance(result, TerminalFailure):
                self._record_terminal_first_attempt(ctx=ctx, failure=result)
                yield terminal_failure_event(result, request_id=ctx.request_id)
                return
            for event in result.events:
                yield event
        except AIBuilderBadRequestException:
            raise
        except PlanningStatePayloadTooLargeError:
            raise
        except Exception as error:
            # A proposal response already came back from the provider. If local
            # compilation or persistence now fails, replay could repeat paid
            # provider work, so the durable turn must remain outcome-unknown.
            # The wrap hides the cause from the client by design; this log is
            # the only place the real failure is observable.
            logger.error(
                "AI Builder proposal compilation or persistence failed after "
                "the provider responded; wrapping into provider-outcome-unknown.",
                exc_info=error,
                extra={"request_id": str(ctx.request_id)},
            )
            # The architecture boundary rejects after compilation, so the
            # capture tap must see the accepted arguments here or the shape
            # that tripped an invariant is unrecoverable (2026-09-05).
            capture_rejected_proposal_arguments(
                arguments,
                session_id=str(ctx.session_id),
                issues=[f"{type(error).__name__}: {error}"],
            )
            raise AIBuilderProviderOutcomeUnknownException() from error

    def _record_terminal_first_attempt(
        self, *, ctx: ProposalTurnContext, failure: TerminalFailure
    ) -> None:
        record_proposal_first_attempt(
            ctx.usage_tracker,
            request_id=ctx.request_id,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            success=False,
            failure_kind=_first_attempt_failure_kind(failure.kind),
        )
        if ctx.usage_tracker is not None:
            ctx.usage_tracker.record_attempt_failure(
                failure_kind=failure.kind, failure_codes=failure.codes
            )

    async def _retry_forced_proposal_after_text(
        self,
        *,
        ctx: ProposalTurnContext,
        correction_message_groups: tuple[ProposalMessageGroup, ...],
        assistant_text: str,
    ) -> tuple[ForcedToolContinuation, ToolRetryConfig]:
        self._record_failed_proposal_attempt_repair(
            usage_tracker=ctx.usage_tracker,
            request_id=ctx.request_id,
            reason="missing_submission_tool",
        )
        retry_config = self._proposal_retry_config(
            target_kind=ctx.target_kind,
            assistant_snapshots=ctx.assistant_snapshots,
            request_id=ctx.request_id,
            planning_state=ctx.planning_state,
            plan_edit_context=ctx.plan_edit_context,
            prior_spec_for_revision=ctx.prior_spec_for_revision,
            usage_tracker=ctx.usage_tracker,
            proposal_tool_schema=ctx.proposal_tool_schema,
            obligation_projection=ctx.obligation_projection,
            compile_context=ctx.compile_context,
        )
        outcome = await run_forced_tool_retry_after_text(
            ForcedToolAfterTextRequest(
                ctx=ctx,
                correction_message_groups=correction_message_groups,
                assistant_text=assistant_text,
                retry_config=retry_config,
                forced_proposal_temperature=self.forced_proposal_temperature,
                repair_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=ctx.usage_tracker,
                    call_kind="forced_tool_continuation",
                    before_provider_call=ctx.before_provider_call,
                ),
                error_phase=AIBuilderErrorPhase.PROPOSAL,
            )
        )
        return outcome, retry_config


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


def _first_attempt_failure_kind(
    kind: ProposalAttemptFailureKind,
) -> ProposalFailureKind | None:
    if kind in ("provider_error", "provider_truncation", "internal_error"):
        return None
    return kind


def _attempt_failure_kind(
    reason: ProposalRepairReason,
) -> ProposalAttemptFailureKind:
    return reason
