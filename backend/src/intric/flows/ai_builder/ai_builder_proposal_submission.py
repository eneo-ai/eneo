"""Own active create/edit proposal submission behavior."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    build_proposal_architecture_error_event,
    record_proposal_architecture_failure,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
    make_provider_safe_server_tool_call_id,
)
from intric.flows.ai_builder.ai_builder_create_proposal import (
    OUTLINE_FLOW_FORCED_TOOL_PROMPT,
    process_outline_arguments,
    process_scoped_step_model_revision_if_requested,
    scoped_model_revision_assistant_text,
)
from intric.flows.ai_builder.ai_builder_discovery_followup import (
    emit_discovery_followup_if_needed,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_edit_proposal import (
    EDIT_FLOW_FORCED_TOOL_PROMPT,
    process_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_repair import (
    repair_compiled_edit_description_if_needed,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import (
    EDIT_FLOW_TOOL_NAME,
    build_edit_flow_tool_schema,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from intric.flows.ai_builder.ai_builder_events import build_text_event
from intric.flows.ai_builder.ai_builder_interaction_utils import analyze_discovery_ready
from intric.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_completion import (
    call_proposal_completion_with_usage,
    make_usage_tracked_proposal_completion,
)
from intric.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from intric.flows.ai_builder.ai_builder_proposal_repair_runtime import (
    ForcedToolAfterTextRequest,
    ProposalSelfCorrectionRequest,
    build_proposal_self_correction_request,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalRepairReason,
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
    record_proposal_first_attempt,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalTurnContext,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    OUTLINE_FLOW_TOOL_NAME,
    active_submission_tool_name,
    build_outline_flow_tool_schema,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)

EventBatch = tuple[dict[str, str], ...]
SUBMISSION_TOOL_NAMES = frozenset({OUTLINE_FLOW_TOOL_NAME, EDIT_FLOW_TOOL_NAME})


@dataclass(frozen=True)
class ForcedSubmissionResponse:
    text_content: str | None
    tool_call: RuntimeToolCall


class LiteLLMProposalMessage(Protocol):
    tool_calls: Sequence[RuntimeToolCall] | None
    content: str | None


def _forced_submission_response(
    *,
    message: LiteLLMProposalMessage,
    submission_tool_name: str,
) -> ForcedSubmissionResponse | None:
    if submission_tool_name not in SUBMISSION_TOOL_NAMES:
        return None

    tool_calls = tuple(message.tool_calls or ())
    if len(tool_calls) != 1:
        return None

    tool_call = tool_calls[0]
    if tool_call.function.name != submission_tool_name:
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
    ) -> None:
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self._compiled_proposal_finalizer = CompiledProposalFinalizer(
            repo=repo,
            quality_retry_warning_codes=quality_retry_warning_codes,
        )

    def _active_submission_tool_schemas(
        self,
        *,
        flow: "Flow | None",
        available_models: list[dict[str, Any]] | None,
        available_kbs: list[dict[str, Any]] | None,
        available_mcps: AIBuilderMCPResourceInput,
        resource_catalog: AIBuilderResourceCatalog | None,
    ) -> list[dict[str, Any]]:
        if flow is None:
            return [
                build_outline_flow_tool_schema(
                    available_models=available_models,
                    available_kbs=available_kbs,
                    available_mcps=available_mcps,
                    resource_catalog=resource_catalog,
                )
            ]
        return [
            build_edit_flow_tool_schema(
                list(flow.steps),
                available_models=available_models,
                available_kbs=available_kbs,
                available_mcps=available_mcps,
                resource_catalog=resource_catalog,
            )
        ]

    def dispatch_submission_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None] | None:
        tool_name = tool_call.function.name
        if tool_name == OUTLINE_FLOW_TOOL_NAME:
            return self._handle_outline_flow_tool_call(ctx=ctx, tool_call=tool_call)
        if tool_name == EDIT_FLOW_TOOL_NAME:
            return self._handle_edit_flow_tool_call(ctx=ctx, tool_call=tool_call)
        return None

    def contains_submission_tool_call(
        self,
        tool_calls: Sequence[RuntimeToolCall],
    ) -> bool:
        return any(call.function.name in SUBMISSION_TOOL_NAMES for call in tool_calls)

    async def run_active_submission_attempt(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        llm_messages: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_models: list[dict[str, Any]] | None,
        available_kbs: list[dict[str, Any]] | None,
        available_mcps: AIBuilderMCPResourceInput,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog | None,
        max_output_tokens: int,
        proposal_temperature: float,
        request_id: str,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        assistant_metadata: dict[str, Any] | None = None,
        planning_state: PlanningState | None = None,
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        submission_tool_name = active_submission_tool_name(
            is_edit_mode=flow is not None
        )
        tool_schemas = self._active_submission_tool_schemas(
            flow=flow,
            available_models=available_models,
            available_kbs=available_kbs,
            available_mcps=available_mcps,
            resource_catalog=resource_catalog,
        )
        usage_tracker = ProposalTurnTelemetry(
            request_id=request_id,
            model=litellm_model,
        )
        ctx = ProposalTurnContext(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            usage_tracker=usage_tracker,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )
        scoped_model_preflight_result = (
            await self._preflight_scoped_model_revision_if_requested(ctx=ctx)
        )
        if scoped_model_preflight_result is not None:
            if scoped_model_preflight_result.user_message is not None:
                yield build_text_event(scoped_model_preflight_result.user_message)
                return
            if scoped_model_preflight_result.has_events:
                for event in scoped_model_preflight_result.iter_events():
                    yield event
                return

        try:
            response = await call_proposal_completion_with_usage(
                litellm_client=self.litellm_client,
                messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=max_output_tokens,
                temperature=proposal_temperature,
                usage_tracker=usage_tracker,
                tool_choice={
                    "type": "function",
                    "function": {"name": submission_tool_name},
                },
            )
        except Exception as error:
            logger.error("AI Builder proposal task failed", exc_info=error)
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.PLANNER,
                request_id=request_id,
            )
            return

        message = response.choices[0].message
        forced_response = _forced_submission_response(
            message=message,
            submission_tool_name=submission_tool_name,
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
            correction_messages=llm_messages,
            assistant_text=message.content or "",
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            usage_tracker=usage_tracker,
            assistant_metadata=assistant_metadata,
        )
        if forced_events is not None:
            for event in forced_events:
                yield event
            return

        yield build_ai_builder_error_event(
            message=(
                "The AI planner did not return a valid flow proposal. "
                "Please try again or use a more capable model."
            ),
            code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING,
            phase=AIBuilderErrorPhase.PROPOSAL,
            request_id=request_id,
        )

    async def _preflight_scoped_model_revision_if_requested(
        self,
        *,
        ctx: ProposalTurnContext,
    ) -> ToolProcessingResult | None:
        if ctx.flow is not None:
            return None

        result = process_scoped_step_model_revision_if_requested(
            conversation=ctx.conversation,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            resource_catalog=ctx.resource_catalog,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
        )
        if result is None or result.compiled_proposal is None:
            if result is not None and result.feedback is not None:
                return ToolProcessingResult(
                    event=build_ai_builder_error_event(
                        message=(
                            "The selected model change could not be applied to "
                            "the current plan. Refresh the plan and try again."
                        ),
                        code=AIBuilderErrorCode.BAD_REQUEST,
                        phase=AIBuilderErrorPhase.PROPOSAL,
                        request_id=ctx.request_id,
                        details={
                            "failure_kind": result.failure_kind or "unknown",
                        },
                    )
                )
            return result

        return await self._compiled_proposal_finalizer.finalize_compiled_proposal(
            CompiledProposalFinalizationRequest(
                turn=ctx.turn,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                arguments={
                    "plan_rationale": result.compiled_proposal.plan_rationale or "",
                    "revision_kind": "scoped_step_model",
                },
                assistant_content=scoped_model_revision_assistant_text(
                    ctx.conversation
                ),
                assistant_metadata=ctx.assistant_metadata,
                tool_call_id=make_provider_safe_server_tool_call_id(
                    kind="scoped_model_revision",
                    stable_key=ctx.request_id,
                ),
                metadata_tool_call=None,
                compiled=result.compiled_proposal,
                resource_catalog=ctx.resource_catalog,
                flow=ctx.flow,
                request_id=ctx.request_id,
                usage_tracker=ctx.usage_tracker,
            )
        )

    def _outline_flow_retry_config(
        self,
        *,
        request_id: str,
        planning_state: PlanningState | None,
        plan_edit_context: AIBuilderPlanEditContext | None,
        prior_plan_for_revision: BuilderPlan | None,
        usage_tracker: ProposalTurnTelemetry | None,
    ) -> ToolRetryConfig:
        async def _process_tool_invocation(
            invocation: ToolRetryInvocation,
        ) -> ToolProcessingResult:
            result = await process_outline_arguments(
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
            if result.compiled_proposal is None:
                return result
            return await self._compiled_proposal_finalizer.finalize_compiled_proposal(
                CompiledProposalFinalizationRequest(
                    turn=invocation.turn,
                    conversation=invocation.conversation,
                    new_messages_start=invocation.new_messages_start,
                    tool_name=OUTLINE_FLOW_TOOL_NAME,
                    arguments=invocation.arguments,
                    assistant_content=invocation.assistant_content,
                    assistant_metadata=invocation.assistant_metadata,
                    tool_call_id=invocation.tool_call_id,
                    metadata_tool_call=None,
                    compiled=result.compiled_proposal,
                    resource_catalog=invocation.resource_catalog,
                    flow=invocation.flow,
                    request_id=request_id,
                    usage_tracker=usage_tracker,
                )
            )

        return ToolRetryConfig(
            target_tool_name=OUTLINE_FLOW_TOOL_NAME,
            forced_tool_prompt=OUTLINE_FLOW_FORCED_TOOL_PROMPT,
            process_tool_invocation=_process_tool_invocation,
        )

    def _edit_flow_retry_config(
        self,
        *,
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        request_id: str,
        plan_edit_context: AIBuilderPlanEditContext | None,
        prior_plan_for_revision: BuilderPlan | None,
        usage_tracker: ProposalTurnTelemetry | None,
    ) -> ToolRetryConfig:
        async def _process_tool_invocation(
            invocation: ToolRetryInvocation,
        ) -> ToolProcessingResult:
            result = await process_edit_arguments(
                turn=invocation.turn,
                conversation=invocation.conversation,
                arguments=invocation.arguments,
                available_model_refs=invocation.available_model_refs,
                available_kb_refs=invocation.available_kb_refs,
                flow=invocation.flow,
                assistant_snapshots=assistant_snapshots,
                resource_catalog=invocation.resource_catalog,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
            )
            if result.compiled_proposal is None:
                return result
            compiled = await repair_compiled_edit_description_if_needed(
                compiled=result.compiled_proposal,
                flow=invocation.flow,
                call_proposal_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=usage_tracker,
                    counts_as_repair=False,
                ),
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=max_output_tokens,
            )
            return await self._compiled_proposal_finalizer.finalize_compiled_proposal(
                CompiledProposalFinalizationRequest(
                    turn=invocation.turn,
                    conversation=invocation.conversation,
                    new_messages_start=invocation.new_messages_start,
                    tool_name=EDIT_FLOW_TOOL_NAME,
                    arguments=invocation.arguments,
                    assistant_content=invocation.assistant_content,
                    assistant_metadata=invocation.assistant_metadata,
                    tool_call_id=invocation.tool_call_id,
                    metadata_tool_call=None,
                    compiled=compiled,
                    resource_catalog=invocation.resource_catalog,
                    flow=invocation.flow,
                    request_id=request_id,
                    usage_tracker=usage_tracker,
                )
            )

        return ToolRetryConfig(
            target_tool_name=EDIT_FLOW_TOOL_NAME,
            forced_tool_prompt=EDIT_FLOW_FORCED_TOOL_PROMPT,
            process_tool_invocation=_process_tool_invocation,
        )

    def _build_self_correction_request(
        self,
        *,
        ctx: ProposalTurnContext,
        error_message: str,
        tool_call: Any,
        retry_config: ToolRetryConfig,
    ) -> ProposalSelfCorrectionRequest:
        return build_proposal_self_correction_request(
            ctx=ctx,
            error_message=error_message,
            tool_call=tool_call,
            retry_config=retry_config,
            self_correction_temperature=self.self_correction_temperature,
            self_correction_bumped_temperature=self.self_correction_bumped_temperature,
            forced_proposal_temperature=self.forced_proposal_temperature,
            repair_completion=make_usage_tracked_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=ctx.usage_tracker,
                counts_as_repair=True,
            ),
        )

    async def _resolve_submission_prerequisite_events(
        self,
        *,
        ctx: ProposalTurnContext,
        requirements_not_confirmed_message: str,
    ) -> tuple[bool, list[dict[str, str]]]:
        requirements_state = resolve_requirements_state(ctx.conversation)
        if requirements_state.confirmed:
            return False, []

        followup_result = await emit_discovery_followup_if_needed(
            repo=self.repo,
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            flow=ctx.flow,
            litellm_client=self.litellm_client,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            assistant_metadata=assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
        )
        if followup_result is not None:
            return True, followup_result.events
        if not analyze_discovery_ready(ctx.conversation, flow=ctx.flow):
            return True, []
        return True, [
            build_ai_builder_error_event(
                message=requirements_not_confirmed_message,
                code=AIBuilderErrorCode.REQUIREMENTS_NOT_CONFIRMED,
                phase=AIBuilderErrorPhase.REQUIREMENTS,
                request_id=ctx.request_id,
            )
        ]

    async def _handle_outline_flow_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        (
            blocked,
            prerequisite_events,
        ) = await self._resolve_submission_prerequisite_events(
            ctx=ctx,
            requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
        )
        for event in prerequisite_events:
            yield event
        if blocked:
            return

        retry_config = self._outline_flow_retry_config(
            request_id=ctx.request_id,
            planning_state=ctx.planning_state,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
            usage_tracker=ctx.usage_tracker,
        )

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                success=False,
                failure_kind="parse",
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                reason="parse",
            )
            async for event in run_tool_self_correction(
                self._build_self_correction_request(
                    ctx=ctx,
                    error_message=f"Invalid outline_flow arguments: {error}",
                    tool_call=tool_call,
                    retry_config=retry_config,
                )
            ):
                yield event
            return

        try:
            outline_result = await process_outline_arguments(
                turn=ctx.turn,
                conversation=ctx.conversation,
                arguments=arguments,
                tool_call_id=tool_call.id,
                available_model_refs=ctx.available_model_refs,
                available_kb_refs=ctx.available_kb_refs,
                resource_catalog=ctx.resource_catalog,
                planning_state=ctx.planning_state,
                plan_edit_context=ctx.plan_edit_context,
                prior_plan_for_revision=ctx.prior_plan_for_revision,
            )
            if outline_result.compiled_proposal is not None:
                outline_result = (
                    await self._compiled_proposal_finalizer.finalize_compiled_proposal(
                        CompiledProposalFinalizationRequest(
                            turn=ctx.turn,
                            conversation=ctx.conversation,
                            new_messages_start=ctx.new_messages_start,
                            tool_name=OUTLINE_FLOW_TOOL_NAME,
                            arguments=arguments,
                            assistant_content="Här är mitt förslag:",
                            assistant_metadata=ctx.assistant_metadata,
                            tool_call_id=tool_call.id,
                            metadata_tool_call=tool_call,
                            compiled=outline_result.compiled_proposal,
                            resource_catalog=ctx.resource_catalog,
                            flow=ctx.flow,
                            request_id=ctx.request_id,
                            usage_tracker=ctx.usage_tracker,
                        )
                    )
                )
        except AIBuilderArchitectureError as error:
            record_proposal_architecture_failure(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
            )
            yield build_proposal_architecture_error_event(
                error,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
            )
            return
        if outline_result.user_message is not None:
            yield build_text_event(outline_result.user_message)
            return
        if not outline_result.has_events:
            proposal_repair_reason = proposal_repair_reason_from_tool_failure(
                outline_result.failure_kind
            )
            record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                success=False,
                failure_kind=proposal_repair_reason,
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                reason=proposal_repair_reason,
            )
            async for event in run_tool_self_correction(
                self._build_self_correction_request(
                    ctx=ctx,
                    error_message=outline_result.feedback
                    or "Invalid outline_flow draft.",
                    tool_call=tool_call,
                    retry_config=retry_config,
                )
            ):
                yield event
            return

        for event in outline_result.iter_events():
            yield event

    async def _retry_forced_proposal_after_text(
        self,
        *,
        correction_messages: list[dict[str, Any]],
        assistant_text: str,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        planning_state: PlanningState | None = None,
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
        usage_tracker: ProposalTurnTelemetry,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> EventBatch | None:
        request_id = usage_tracker.request_id
        target_tool_name = active_submission_tool_name(is_edit_mode=flow is not None)
        record_proposal_first_attempt(
            usage_tracker,
            request_id=request_id,
            tool_name=target_tool_name,
            success=False,
            failure_kind="missing_submission_tool",
        )
        _record_proposal_repair_invocation(
            usage_tracker,
            request_id=request_id,
            tool_name=target_tool_name,
            reason="missing_submission_tool",
        )
        retry_config = (
            self._outline_flow_retry_config(
                request_id=request_id,
                planning_state=planning_state,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
                usage_tracker=usage_tracker,
            )
            if flow is None
            else self._edit_flow_retry_config(
                assistant_snapshots=assistant_snapshots,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=max_output_tokens,
                request_id=request_id,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
                usage_tracker=usage_tracker,
            )
        )
        outcome = await run_forced_tool_retry_after_text(
            ForcedToolAfterTextRequest(
                correction_messages=correction_messages,
                assistant_text=assistant_text,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                turn=turn,
                conversation=conversation,
                new_messages_start=new_messages_start,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                retry_config=retry_config,
                forced_proposal_temperature=self.forced_proposal_temperature,
                repair_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=usage_tracker,
                    counts_as_repair=True,
                ),
                resource_catalog=resource_catalog,
                flow=flow,
                build_assistant_metadata=(
                    lambda: assistant_metadata_with_usage(
                        conversation=conversation,
                        base_metadata=assistant_metadata,
                        usage_tracker=usage_tracker,
                    )
                ),
                request_id=request_id,
                usage_tracker=usage_tracker,
            )
        )
        return outcome.events

    async def _handle_edit_flow_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        # Edit submissions operate on an existing flow; discovery prerequisites
        # belong to create submissions before the first plan exists.
        retry_config = self._edit_flow_retry_config(
            assistant_snapshots=ctx.assistant_snapshots,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            max_output_tokens=ctx.max_output_tokens,
            request_id=ctx.request_id,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
            usage_tracker=ctx.usage_tracker,
        )
        try:
            raw_args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=EDIT_FLOW_TOOL_NAME,
                success=False,
                failure_kind="parse",
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=EDIT_FLOW_TOOL_NAME,
                reason="parse",
            )
            async for event in run_tool_self_correction(
                self._build_self_correction_request(
                    ctx=ctx,
                    error_message=f"Invalid edit_flow arguments: {error}",
                    tool_call=tool_call,
                    retry_config=retry_config,
                )
            ):
                yield event
            return

        edit_result = await process_edit_arguments(
            turn=ctx.turn,
            conversation=ctx.conversation,
            arguments=raw_args,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            flow=ctx.flow,
            assistant_snapshots=ctx.assistant_snapshots,
            resource_catalog=ctx.resource_catalog,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
        )
        if edit_result.compiled_proposal is not None:
            compiled = await repair_compiled_edit_description_if_needed(
                compiled=edit_result.compiled_proposal,
                flow=ctx.flow,
                call_proposal_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=ctx.usage_tracker,
                    counts_as_repair=False,
                ),
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
                max_output_tokens=ctx.max_output_tokens,
            )
            edit_result = (
                await self._compiled_proposal_finalizer.finalize_compiled_proposal(
                    CompiledProposalFinalizationRequest(
                        turn=ctx.turn,
                        conversation=ctx.conversation,
                        new_messages_start=ctx.new_messages_start,
                        tool_name=EDIT_FLOW_TOOL_NAME,
                        arguments=raw_args,
                        assistant_content=ctx.text_content or "",
                        assistant_metadata=ctx.assistant_metadata,
                        tool_call_id=tool_call.id,
                        metadata_tool_call=tool_call,
                        compiled=compiled,
                        resource_catalog=ctx.resource_catalog,
                        flow=ctx.flow,
                        request_id=ctx.request_id,
                        usage_tracker=ctx.usage_tracker,
                    )
                )
            )
        if edit_result.event is None:
            proposal_repair_reason = proposal_repair_reason_from_tool_failure(
                edit_result.failure_kind
            )
            record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=EDIT_FLOW_TOOL_NAME,
                success=False,
                failure_kind=proposal_repair_reason,
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=EDIT_FLOW_TOOL_NAME,
                reason=proposal_repair_reason,
            )
            async for event in run_tool_self_correction(
                self._build_self_correction_request(
                    ctx=ctx,
                    error_message=edit_result.feedback
                    or "Invalid edit_flow arguments.",
                    tool_call=tool_call,
                    retry_config=retry_config,
                )
            ):
                yield event
            return

        yield edit_result.event


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
