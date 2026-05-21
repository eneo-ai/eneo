from __future__ import annotations

import json
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
)
from uuid import UUID

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_proposal import (
    outline_flow_retry_config,
    process_outline_arguments,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_followup import (
    BackendQuestionPersistenceResult,
    emit_discovery_followup_if_needed,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_block_message_runtime,
)
from intric.flows.ai_builder.ai_builder_edit_proposal import (
    edit_flow_retry_config,
    process_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import (
    EDIT_FLOW_TOOL_NAME,
    build_edit_flow_tool_schema,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
    coerce_ai_builder_error_code,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_requirements_summary_event,
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    is_supported_structured_question_id,
    normalize_requirements_summary_for_flow,
    normalize_structured_question_payload,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    analyze_discovery_ready,
    build_question_fallback_text,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    build_mcp_resource_selection_question,
    find_mcp_usage_without_selection_issue,
    find_named_mcp_reference_issue,
    find_named_mcp_request_issue,
    mcp_selection_answer_allows_planning,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    ConversationMessage,
    FlowDraftSpecCore,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    request_self_correction as run_request_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    retry_forced_tool_after_text as run_retry_forced_tool_after_text,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    log_proposal_first_attempt,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_repair_transport import (
    append_tool_retry_feedback_turn,
    build_persisted_tool_call_stub,
    build_tool_retry_messages,
    persist_tool_turn,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    OUTLINE_FLOW_TOOL_NAME,
    build_discovery_complete_tool_schemas,
    build_outline_flow_tool_schema,
    parse_confirm_requirements,
    parse_structured_question,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)
MAX_SELF_CORRECTION_RETRIES = 3
SUBMISSION_TOOL_NAMES = frozenset({OUTLINE_FLOW_TOOL_NAME, EDIT_FLOW_TOOL_NAME})
EventBatch = tuple[dict[str, str], ...]


def _tool_calls_contain_submission(tool_calls: list[Any]) -> bool:
    return any(
        getattr(getattr(call, "function", None), "name", None) in SUBMISSION_TOOL_NAMES
        for call in tool_calls
    )


def _assistant_metadata_with_usage(
    *,
    conversation: list[ConversationMessage],
    base_metadata: dict[str, Any] | None,
    usage_tracker: ProposalTurnTelemetry | None,
    tool_calls: list[Any] | None = None,
) -> dict[str, Any] | None:
    if usage_tracker is None:
        return base_metadata
    return build_assistant_message_metadata(
        conversation,
        planner_telemetry=usage_tracker.build_planner_telemetry(
            tool_call_count=len(tool_calls or [])
        ),
        base_metadata=base_metadata,
        tool_calls=tool_calls,
    )


def _record_proposal_first_attempt(
    usage_tracker: ProposalTurnTelemetry | None,
    *,
    request_id: str,
    tool_name: str,
    success: bool,
    failure_kind: ProposalFailureKind | None = None,
) -> None:
    if usage_tracker is None:
        return
    if usage_tracker.record_first_attempt(
        tool_name=tool_name,
        success=success,
        failure_kind=failure_kind,
    ):
        log_proposal_first_attempt(
            request_id=request_id,
            tool_name=tool_name,
            success=success,
            failure_kind=failure_kind,
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


def _record_proposal_architecture_failure(
    usage_tracker: ProposalTurnTelemetry | None,
    *,
    request_id: str | None,
    tool_name: str,
) -> None:
    if usage_tracker is None:
        return
    _record_proposal_first_attempt(
        usage_tracker,
        request_id=request_id or usage_tracker.request_id,
        tool_name=tool_name,
        success=False,
        failure_kind="architecture",
    )


def _build_architecture_error_event(
    error: AIBuilderArchitectureError,
    *,
    request_id: str | None,
    tool_name: str,
) -> dict[str, str]:
    log_extra = error.log_extra()
    log_extra["tool_name"] = tool_name
    if request_id is not None:
        log_extra["request_id"] = request_id
    logger.error(
        "ai_builder_architecture_error",
        extra=log_extra,
    )
    return build_ai_builder_error_event(
        message=(
            "The AI planner could not build a valid flow from the confirmed "
            "requirements. Please adjust the requirements and try again."
        ),
        code=coerce_ai_builder_error_code(error.public_code),
        phase=AIBuilderErrorPhase.PROPOSAL,
        request_id=request_id,
    )


def _self_correction_user_message(
    *,
    feedback: str | None,
    failure_kind: ToolProcessingFailureKind | None,
) -> str:
    details = (feedback or "").casefold()
    if failure_kind in {"parse", "recoverable_parse"}:
        return (
            "The AI Builder returned an incomplete plan configuration and could "
            "not repair it automatically. Try again, or use a more capable model "
            "if the same error repeats."
        )
    if "flow must have at least one step" in details or "empty_steps" in details:
        return (
            "The corrected plan did not contain any flow steps. Ask for at least "
            "one concrete step, such as transcribing audio or summarizing text, "
            "then try again."
        )
    if (
        "input_source 'flow_input'" in details
        or "runtime_upload" in details
        or "first step" in details
    ):
        return (
            "The corrected plan still could not connect the flow input to the "
            "first step. For audio or file flows, the first step must receive the "
            "uploaded file at runtime before later steps analyze the result."
        )
    if failure_kind == "quality":
        return (
            "The corrected plan still failed the AI Builder quality checks. "
            "Revise the request with the exact input, output, and main steps you "
            "want, then try again."
        )
    return (
        "The corrected plan is still not a valid flow. Revise the request with "
        "the input, output, and the concrete steps the flow should contain, then "
        "try again."
    )


def _conversation_user_text(conversation: list[ConversationMessage]) -> str:
    return "\n".join(
        message.content
        for message in conversation
        if message.role == "user" and message.content
    )


@dataclass(frozen=True)
class ProposalContext:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    llm_messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None
    max_output_tokens: int
    request_id: str
    flow: "Flow | None" = None
    assistant_snapshots: AssistantAuthoringSnapshots | None = None
    text_content: str | None = None
    assistant_metadata: dict[str, Any] | None = None
    planning_state: PlanningState | None = None
    usage_tracker: ProposalTurnTelemetry | None = None
    plan_edit_context: AIBuilderPlanEditContext | None = None
    prior_plan_for_revision: BuilderPlan | None = None

    @property
    def session_id(self) -> UUID:
        return self.turn.session_id

    @property
    def base_planning_state_version(self) -> int:
        return self.turn.base_planning_state_version


@dataclass(frozen=True)
class SubmissionToolHandlerConfig:
    target_tool_name: str
    requirements_not_confirmed_message: str
    parse_error_prefix: str
    invalid_result_message: str
    forced_tool_prompt: str
    process_submission_arguments: Callable[
        ...,
        Awaitable[ToolProcessingResult],
    ]
    include_flow_context: bool = False


class AIBuilderProposalProcessor:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        self_correction_bumped_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self.quality_retry_warning_codes = quality_retry_warning_codes

    async def mcp_clarification_events_if_needed(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        spec: FlowDraftSpecCore,
        resource_catalog: AIBuilderResourceCatalog | None,
        flow: "Flow | None",
        assistant_metadata: dict[str, Any] | None = None,
        assistant_metadata_builder: Callable[[], dict[str, Any] | None] | None = None,
    ) -> BackendQuestionPersistenceResult | None:
        if resource_catalog is None or mcp_selection_answer_allows_planning(
            conversation
        ):
            return None

        issue = find_named_mcp_reference_issue(
            spec=spec,
            catalog=resource_catalog,
            signal_text=aggregate_freeform_user_text(conversation),
        )
        if issue is None:
            issue = find_mcp_usage_without_selection_issue(
                spec=spec,
                catalog=resource_catalog,
            )
        if issue is None:
            return None

        metadata = (
            assistant_metadata_builder()
            if assistant_metadata_builder is not None
            else assistant_metadata
        )
        question_data, assistant_text = build_mcp_resource_selection_question(
            issue=issue,
            catalog=resource_catalog,
            language=resolve_ui_language(conversation) or "sv",
        )
        logger.info(
            "ai_builder_mcp_selection_requires_clarification "
            "session_id=%s step_ref=%s requested_mcp=%s reason=%s selected_server_refs=%s",
            turn.session_id,
            issue.step_ref,
            issue.requested_name,
            issue.reason,
            sorted(issue.selected_server_refs),
        )
        return await persist_backend_question(
            repo=self.repo,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            question_data=question_data,
            assistant_text=assistant_text,
            assistant_metadata=metadata,
            tool_content=(
                "MCP selection question presented because MCP usage requires explicit "
                "user selection from enabled space resources."
            ),
            flow=flow,
        )

    @staticmethod
    def _build_self_correction_error_event(
        *,
        feedback: str | None,
        failure_kind: ToolProcessingFailureKind | None,
        request_id: str | None = None,
    ) -> dict[str, str]:
        message = _self_correction_user_message(
            feedback=feedback,
            failure_kind=failure_kind,
        )
        if failure_kind in {"parse", "recoverable_parse"}:
            code = AIBuilderErrorCode.SELF_CORRECTION_INVALID_PAYLOAD
        elif failure_kind == "quality":
            code = AIBuilderErrorCode.SELF_CORRECTION_QUALITY_FAILURE
        else:
            code = AIBuilderErrorCode.SELF_CORRECTION_INVALID_PLAN
        return build_ai_builder_error_event(
            message=message,
            code=code,
            phase=AIBuilderErrorPhase.SELF_CORRECTION,
            request_id=request_id,
        )

    async def handle_tool_call(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_calls: list[Any],
        text_content: str | None,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        request_id: str,
        assistant_metadata: dict[str, Any] | None = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        planning_state: PlanningState | None = None,
        usage_tracker: ProposalTurnTelemetry | None = None,
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        ctx = ProposalContext(
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
            text_content=text_content,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            usage_tracker=usage_tracker,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )
        if ctx.text_content and not _tool_calls_contain_submission(tool_calls):
            yield build_text_event(ctx.text_content)

        for tool_call in tool_calls:
            dispatched = self._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
            if dispatched is None:
                continue
            async for event in dispatched:
                yield event

    async def propose_plan(
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
        available_mcps: AIBuilderMCPResourceInput = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the server-selected plan proposal task.

        This is deliberately narrower than the planner contract: the
        server already selected `propose_plan`, so the model only fills
        the create/edit tool payload.
        """

        submission_tool_name = _active_submission_tool_name(flow)
        preflight_result = await self._mcp_preflight_events_if_needed(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            resource_catalog=resource_catalog,
            flow=flow,
            assistant_metadata=assistant_metadata,
        )
        if preflight_result is not None:
            for event in preflight_result.events:
                yield event
            return

        tool_schemas = _active_submission_tool_schemas(
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
        try:
            response = await self._call_proposal_completion_with_usage(
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
        tool_calls = message.tool_calls if hasattr(message, "tool_calls") else None
        if tool_calls:
            yielded = False
            async for event in self.handle_tool_call(
                turn=turn,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_calls=tool_calls,
                text_content=message.content,
                llm_messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                resource_catalog=resource_catalog,
                max_output_tokens=max_output_tokens,
                request_id=request_id,
                assistant_metadata=assistant_metadata,
                flow=flow,
                assistant_snapshots=assistant_snapshots,
                planning_state=planning_state,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
                usage_tracker=usage_tracker,
            ):
                yielded = True
                yield event
            if yielded:
                return

        _record_proposal_first_attempt(
            usage_tracker,
            request_id=request_id,
            tool_name=submission_tool_name,
            success=False,
            failure_kind="missing_submission_tool",
        )
        _record_proposal_repair_invocation(
            usage_tracker,
            request_id=request_id,
            tool_name=submission_tool_name,
            reason="missing_submission_tool",
        )
        forced_events = await self.retry_forced_proposal_after_text(
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

    def _dispatch_known_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None] | None:
        tool_name = tool_call.function.name
        if tool_name == ASK_STRUCTURED_QUESTION_TOOL_NAME:
            return self._handle_structured_question(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == OUTLINE_FLOW_TOOL_NAME:
            return self._handle_outline_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME:
            return self._handle_confirm_requirements(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == EDIT_FLOW_TOOL_NAME:
            return self._handle_edit_flow(
                ctx=ctx,
                tool_call=tool_call,
            )
        return None

    async def _mcp_preflight_events_if_needed(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        resource_catalog: AIBuilderResourceCatalog | None,
        flow: "Flow | None",
        assistant_metadata: dict[str, Any] | None,
    ) -> BackendQuestionPersistenceResult | None:
        if resource_catalog is None or mcp_selection_answer_allows_planning(
            conversation
        ):
            return None

        issue = find_named_mcp_request_issue(
            catalog=resource_catalog,
            signal_text=_conversation_user_text(conversation),
        )
        if issue is None:
            return None

        question_data, assistant_text = build_mcp_resource_selection_question(
            issue=issue,
            catalog=resource_catalog,
            language=resolve_ui_language(conversation) or "sv",
        )
        logger.info(
            "ai_builder_mcp_preflight_requires_clarification "
            "session_id=%s requested_mcp=%s",
            turn.session_id,
            issue.requested_name,
        )
        return await persist_backend_question(
            repo=self.repo,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            question_data=question_data,
            assistant_text=assistant_text,
            assistant_metadata=assistant_metadata,
            tool_content=(
                "MCP selection question presented before proposal because the user "
                "requested an MCP by name and must choose from enabled space MCP resources."
            ),
            flow=flow,
        )

    async def _resolve_submission_prerequisite_events(
        self,
        *,
        ctx: ProposalContext,
        requirements_not_confirmed_message: str,
    ) -> tuple[bool, list[dict[str, str]]]:
        requirements_state = resolve_requirements_state(ctx.conversation)
        if requirements_state.confirmed:
            return False, []

        followup_result = await self.emit_discovery_followup_if_needed(
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            assistant_metadata=_assistant_metadata_with_usage(
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

    async def _handle_submission_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
        config: SubmissionToolHandlerConfig,
    ) -> AsyncGenerator[dict[str, str], None]:
        (
            blocked,
            prerequisite_events,
        ) = await self._resolve_submission_prerequisite_events(
            ctx=ctx,
            requirements_not_confirmed_message=config.requirements_not_confirmed_message,
        )
        for event in prerequisite_events:
            yield event
        if blocked:
            return

        def _build_retry_config() -> ToolRetryConfig:
            return self._submission_retry_config(
                flow=ctx.flow,
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
                max_output_tokens=ctx.max_output_tokens,
                assistant_snapshots=ctx.assistant_snapshots,
                planning_state=ctx.planning_state,
                plan_edit_context=ctx.plan_edit_context,
                prior_plan_for_revision=ctx.prior_plan_for_revision,
            )

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            _record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
                success=False,
                failure_kind="parse",
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
                reason="parse",
            )
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"{config.parse_error_prefix}: {error}",
                tool_call=tool_call,
                retry_config=_build_retry_config(),
            ):
                yield event
            return

        def _record_successful_proposal() -> None:
            _record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
                success=True,
            )

        def _build_assistant_metadata() -> dict[str, Any] | None:
            return _assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
                tool_calls=[tool_call],
            )

        submission_kwargs = self._build_submission_processing_kwargs(
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=arguments,
            assistant_content="Här är mitt förslag:",
            assistant_metadata=None,
            assistant_metadata_builder=_build_assistant_metadata,
            proposal_success_recorder=_record_successful_proposal,
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            resource_catalog=ctx.resource_catalog,
            flow=ctx.flow,
            include_flow_context=config.include_flow_context,
        )
        if config.target_tool_name == OUTLINE_FLOW_TOOL_NAME:
            submission_kwargs["planning_state"] = ctx.planning_state
            submission_kwargs["plan_edit_context"] = ctx.plan_edit_context
            submission_kwargs["prior_plan_for_revision"] = ctx.prior_plan_for_revision
        try:
            submission_result = await config.process_submission_arguments(
                **submission_kwargs
            )
        except AIBuilderArchitectureError as error:
            _record_proposal_architecture_failure(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
            )
            yield _build_architecture_error_event(
                error,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
            )
            return
        if not submission_result.has_events:
            proposal_repair_reason = proposal_repair_reason_from_tool_failure(
                submission_result.failure_kind
            )
            _record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
                success=False,
                failure_kind=proposal_repair_reason,
            )
            _record_proposal_repair_invocation(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=config.target_tool_name,
                reason=proposal_repair_reason,
            )
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=submission_result.feedback
                or config.invalid_result_message,
                tool_call=tool_call,
                retry_config=_build_retry_config(),
            ):
                yield event
            return

        _record_successful_proposal()
        for event in submission_result.iter_events():
            yield event

    @staticmethod
    def _build_submission_processing_kwargs(
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        arguments: dict[str, Any],
        assistant_content: str,
        assistant_metadata: dict[str, Any] | None = None,
        assistant_metadata_builder: Callable[[], dict[str, Any] | None] | None = None,
        proposal_success_recorder: Callable[[], None] | None = None,
        tool_call_id: str,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog | None,
        flow: "Flow | None",
        include_flow_context: bool,
    ) -> dict[str, Any]:
        processing_kwargs: dict[str, Any] = {
            "turn": turn,
            "conversation": conversation,
            "new_messages_start": new_messages_start,
            "arguments": arguments,
            "assistant_content": assistant_content,
            "assistant_metadata": assistant_metadata,
            "assistant_metadata_builder": assistant_metadata_builder,
            "proposal_success_recorder": proposal_success_recorder,
            "tool_call_id": tool_call_id,
            "available_model_refs": available_model_refs,
            "available_kb_refs": available_kb_refs,
            "resource_catalog": resource_catalog,
        }
        if include_flow_context:
            processing_kwargs["flow"] = flow
        return processing_kwargs

    async def _handle_outline_flow_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        retry_config = outline_flow_retry_config(processor=self)

        async def _process_outline_submission(
            **kwargs: Any,
        ) -> ToolProcessingResult:
            return await process_outline_arguments(processor=self, **kwargs)

        async for event in self._handle_submission_tool_call(
            ctx=ctx,
            tool_call=tool_call,
            config=SubmissionToolHandlerConfig(
                target_tool_name=OUTLINE_FLOW_TOOL_NAME,
                requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
                parse_error_prefix="Invalid outline_flow arguments",
                invalid_result_message="Invalid outline_flow draft.",
                forced_tool_prompt=retry_config.forced_tool_prompt,
                process_submission_arguments=_process_outline_submission,
            ),
        ):
            yield event

    async def call_proposal_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        provider_kwargs = dict(litellm_kwargs)
        provider_kwargs.pop("drop_params", None)
        dropped_response_format = provider_kwargs.pop("response_format", None)
        if dropped_response_format is not None:
            logger.debug("ai_builder_proposal_completion_dropped_response_format")

        return await self.litellm_client.acompletion(
            model=litellm_model,
            messages=messages,
            tools=tool_schemas,
            tool_choice=tool_choice,
            stream=False,
            drop_params=True,
            max_tokens=max_output_tokens,
            temperature=temperature,
            **provider_kwargs,
        )

    async def _call_proposal_completion_with_usage(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
        usage_tracker: ProposalTurnTelemetry | None,
        tool_choice: dict[str, Any] | None = None,
        counts_as_repair: bool = False,
    ) -> Any:
        response = await self.call_proposal_completion(
            messages=messages,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
        )
        if usage_tracker is not None:
            usage_tracker.record_response(
                response,
                messages=messages,
                counts_as_repair=counts_as_repair,
            )
        return response

    async def request_self_correction(
        self,
        *,
        turn: SessionSendTurn,
        request_id: str,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        error_message: str,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        ctx = ProposalContext(
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
        )
        retry_config = self._submission_retry_config(
            flow=flow,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            assistant_snapshots=assistant_snapshots,
        )
        async for event in self._request_tool_self_correction(
            ctx=ctx,
            error_message=error_message,
            tool_call=tool_call,
            retry_config=retry_config,
        ):
            yield event

    async def _request_tool_self_correction(
        self,
        *,
        ctx: ProposalContext,
        error_message: str,
        tool_call: Any,
        retry_config: ToolRetryConfig,
    ) -> AsyncGenerator[dict[str, str], None]:
        def _build_assistant_metadata() -> dict[str, Any] | None:
            return _assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
            )

        async def _call_proposal_completion(**kwargs: Any) -> Any:
            return await self._call_proposal_completion_with_usage(
                **kwargs,
                usage_tracker=ctx.usage_tracker,
                counts_as_repair=True,
            )

        async def _retry_forced_tool_after_text(
            **kwargs: Any,
        ) -> ForcedToolRetryOutcome:
            kwargs.setdefault("request_id", ctx.request_id)
            return await self.retry_forced_tool_after_text(
                **kwargs,
                usage_tracker=ctx.usage_tracker,
            )

        try:
            async for event in run_request_self_correction(
                turn=ctx.turn,
                request_id=ctx.request_id,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                error_message=error_message,
                llm_messages=ctx.llm_messages,
                tool_call=tool_call,
                tool_schemas=ctx.tool_schemas,
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
                available_model_refs=ctx.available_model_refs,
                available_kb_refs=ctx.available_kb_refs,
                max_output_tokens=ctx.max_output_tokens,
                self_correction_temperature=self.self_correction_temperature,
                self_correction_bumped_temperature=(
                    self.self_correction_bumped_temperature
                ),
                max_self_correction_retries=MAX_SELF_CORRECTION_RETRIES,
                call_proposal_completion=_call_proposal_completion,
                process_tool_invocation=retry_config.process_tool_invocation,
                target_tool_name=retry_config.target_tool_name,
                forced_tool_prompt=retry_config.forced_tool_prompt,
                build_self_correction_error_event=(
                    self._build_self_correction_error_event
                ),
                retry_forced_tool_after_text=_retry_forced_tool_after_text,
                resource_catalog=ctx.resource_catalog,
                flow=ctx.flow,
                build_assistant_metadata=_build_assistant_metadata,
            ):
                yield event
        except AIBuilderArchitectureError as error:
            _record_proposal_architecture_failure(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=retry_config.target_tool_name,
            )
            yield _build_architecture_error_event(
                error,
                request_id=ctx.request_id,
                tool_name=retry_config.target_tool_name,
            )

    async def retry_forced_tool_after_text(
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
        target_tool_name: str,
        forced_tool_prompt: str,
        process_tool_invocation: Callable[
            [ToolRetryInvocation], Awaitable[ToolProcessingResult]
        ],
        flow: "Flow | None" = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        usage_tracker: ProposalTurnTelemetry | None = None,
        request_id: str | None = None,
        build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
    ) -> ForcedToolRetryOutcome:
        async def _call_proposal_completion(**kwargs: Any) -> Any:
            return await self._call_proposal_completion_with_usage(
                **kwargs,
                usage_tracker=usage_tracker,
                counts_as_repair=True,
            )

        try:
            return await run_retry_forced_tool_after_text(
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
                target_tool_name=target_tool_name,
                forced_tool_prompt=forced_tool_prompt,
                forced_proposal_temperature=self.forced_proposal_temperature,
                call_proposal_completion=_call_proposal_completion,
                process_tool_invocation=process_tool_invocation,
                resource_catalog=resource_catalog,
                flow=flow,
                build_assistant_metadata=build_assistant_metadata,
                request_id=request_id,
            )
        except AIBuilderArchitectureError as error:
            resolved_request_id = request_id or (
                usage_tracker.request_id if usage_tracker is not None else None
            )
            _record_proposal_architecture_failure(
                usage_tracker,
                request_id=resolved_request_id,
                tool_name=target_tool_name,
            )
            return ForcedToolRetryOutcome(
                events=(
                    _build_architecture_error_event(
                        error,
                        request_id=resolved_request_id,
                        tool_name=target_tool_name,
                    ),
                )
            )

    async def retry_forced_proposal_after_text(
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
        usage_tracker: ProposalTurnTelemetry | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> EventBatch | None:
        retry_config = self._submission_retry_config(
            flow=flow,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            assistant_snapshots=assistant_snapshots,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )
        outcome = await self.retry_forced_tool_after_text(
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
            target_tool_name=retry_config.target_tool_name,
            forced_tool_prompt=retry_config.forced_tool_prompt,
            process_tool_invocation=retry_config.process_tool_invocation,
            resource_catalog=resource_catalog,
            flow=flow,
            usage_tracker=usage_tracker,
            request_id=usage_tracker.request_id if usage_tracker is not None else None,
            build_assistant_metadata=(
                lambda: _assistant_metadata_with_usage(
                    conversation=conversation,
                    base_metadata=assistant_metadata,
                    usage_tracker=usage_tracker,
                )
            ),
        )
        return outcome.events

    async def request_non_question_continuation(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        original_question_id: str | None = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        usage_tracker: ProposalTurnTelemetry | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        submission_tool_name = _active_submission_tool_name(flow)
        filtered_tool_schemas = [
            schema
            for schema in tool_schemas
            if schema.get("function", {}).get("name")
            != ASK_STRUCTURED_QUESTION_TOOL_NAME
        ]
        discovery_ready = analyze_discovery_ready(conversation, flow=flow)
        if not filtered_tool_schemas:
            followup_result = await self.emit_discovery_followup_if_needed(
                turn=turn,
                conversation=conversation,
                new_messages_start=new_messages_start,
                flow=flow,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                assistant_metadata=_assistant_metadata_with_usage(
                    conversation=conversation,
                    base_metadata=None,
                    usage_tracker=usage_tracker,
                    tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                ),
            )
            if followup_result is not None:
                for event in followup_result.events:
                    yield event
                return

            if discovery_ready:
                filtered_tool_schemas = build_discovery_complete_tool_schemas()
            if not filtered_tool_schemas:
                yield build_ai_builder_error_event(
                    message=(
                        "The AI planner lost track of the next clarification step. "
                        "Please try again."
                    ),
                    code=AIBuilderErrorCode.QUESTION_RECOVERY_UNAVAILABLE,
                    phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
                )
                return

        yield build_status_event("repairing")
        forced_tool_choice = (
            {"type": "function", "function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}}
            if discovery_ready
            else None
        )
        correction_messages = build_tool_retry_messages(
            llm_messages=llm_messages,
            tool_call=tool_call,
            tool_feedback=(
                "Structured discovery questions are backend-owned. "
                f"Do not call {ASK_STRUCTURED_QUESTION_TOOL_NAME} again"
                + (
                    f" for question_id '{original_question_id}'."
                    if original_question_id
                    else "."
                )
                + " Continue without inventing a new user-facing question. "
                "If enough information exists, call confirm_requirements. "
                f"If requirements are already confirmed, call {submission_tool_name}. "
                "Otherwise ask for clarification in concise free text only."
            ),
        )

        retries_remaining = 1
        active_messages = correction_messages
        while True:
            try:
                response = await self._call_proposal_completion_with_usage(
                    messages=active_messages,
                    tool_schemas=filtered_tool_schemas,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    max_output_tokens=max_output_tokens,
                    temperature=self.self_correction_temperature,
                    usage_tracker=usage_tracker,
                    tool_choice=forced_tool_choice,
                    counts_as_repair=True,
                )
            except Exception as error:
                logger.error(
                    "Unexpected structured-question continuation retry failed",
                    exc_info=error,
                )
                yield build_ai_builder_error_event(
                    message="The AI planner failed. Please try again.",
                    code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                    phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
                )
                return

            message = response.choices[0].message
            tool_calls = message.tool_calls if hasattr(message, "tool_calls") else None
            if tool_calls:
                repeated_question_call = next(
                    (
                        tc
                        for tc in tool_calls
                        if tc.function.name == ASK_STRUCTURED_QUESTION_TOOL_NAME
                    ),
                    None,
                )
                if repeated_question_call is not None:
                    if retries_remaining <= 0:
                        yield build_ai_builder_error_event(
                            message="The AI planner kept proposing unsupported discovery questions.",
                            code=AIBuilderErrorCode.QUESTION_RECOVERY_EXHAUSTED,
                            phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
                        )
                        return
                    retries_remaining -= 1
                    active_messages = append_tool_retry_feedback_turn(
                        llm_messages=active_messages,
                        tool_call=repeated_question_call,
                        assistant_content=message.content,
                        tool_feedback=(
                            "Structured discovery questions remain backend-owned. "
                            "Do not call ask_structured_question. "
                            f"Continue with confirm_requirements, {submission_tool_name}, or concise free text only."
                        ),
                    )
                    continue

                async for event in self.handle_tool_call(
                    turn=turn,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    tool_calls=tool_calls,
                    text_content=message.content,
                    llm_messages=active_messages,
                    tool_schemas=filtered_tool_schemas,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    available_model_refs=available_model_refs,
                    available_kb_refs=available_kb_refs,
                    resource_catalog=resource_catalog,
                    max_output_tokens=max_output_tokens,
                    request_id="question-recovery",
                    flow=flow,
                    assistant_snapshots=assistant_snapshots,
                    usage_tracker=usage_tracker,
                ):
                    yield event
                return

            if message.content:
                yield build_text_event(message.content)
            return

    async def _handle_structured_question(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        followup_result = await self.emit_discovery_followup_if_needed(
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            assistant_metadata=_assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
        )
        if followup_result is not None:
            for event in followup_result.events:
                yield event
            return

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            yield build_ai_builder_error_event(
                message=f"Invalid question: {error}",
                code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
                phase=AIBuilderErrorPhase.QUESTION,
            )
            return

        try:
            question_data = parse_structured_question(arguments)
        except ValueError:
            fallback_text = build_question_fallback_text(arguments)
            if not fallback_text:
                yield build_ai_builder_error_event(
                    message="Invalid question: could not build fallback prompt",
                    code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
                    phase=AIBuilderErrorPhase.QUESTION,
                )
                return

            await persist_tool_turn(
                repo=self.repo,
                turn=ctx.turn,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                tool_call=tool_call,
                arguments=arguments,
                tool_content=(
                    "Structured question payload was invalid; rendered fallback text question."
                ),
                assistant_metadata=_assistant_metadata_with_usage(
                    conversation=ctx.conversation,
                    base_metadata=ctx.assistant_metadata,
                    usage_tracker=ctx.usage_tracker,
                    tool_calls=[tool_call],
                ),
                flow=ctx.flow,
            )
            yield build_text_event(fallback_text)
            return

        question_data = normalize_structured_question_payload(question_data)
        question_id = question_data["question_id"]
        registry_followup = (
            build_registry_question_followup(
                question_id,
                ctx.conversation,
                flow=ctx.flow,
            )
            if is_supported_structured_question_id(question_id)
            else None
        )
        if registry_followup is not None:
            backend_question_data, assistant_text = registry_followup
            persisted_question = await persist_backend_question(
                repo=self.repo,
                turn=ctx.turn,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                question_data=backend_question_data,
                assistant_text=assistant_text,
                assistant_metadata=_assistant_metadata_with_usage(
                    conversation=ctx.conversation,
                    base_metadata=ctx.assistant_metadata,
                    usage_tracker=ctx.usage_tracker,
                    tool_calls=[tool_call],
                ),
                tool_content=(
                    "Backend-owned discovery question presented to user after model signal."
                ),
                flow=ctx.flow,
            )
            for event in persisted_question.events:
                yield event
            return

        async for event in self.request_non_question_continuation(
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            llm_messages=ctx.llm_messages,
            tool_call=tool_call,
            tool_schemas=ctx.tool_schemas,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            resource_catalog=ctx.resource_catalog,
            max_output_tokens=ctx.max_output_tokens,
            flow=ctx.flow,
            original_question_id=question_id,
            assistant_snapshots=ctx.assistant_snapshots,
            usage_tracker=ctx.usage_tracker,
        ):
            yield event

    async def _process_confirm_requirements_arguments(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        arguments: dict[str, Any],
        assistant_content: str,
        tool_call_id: str,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        flow: "Flow | None" = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        assistant_metadata: dict[str, Any] | None = None,
    ) -> ToolProcessingResult:
        del assistant_content, available_model_refs, available_kb_refs

        try:
            requirements_data = parse_confirm_requirements(arguments)
        except ValueError as error:
            return ToolProcessingResult(
                feedback=f"Invalid requirements summary: {error}",
                failure_kind="parse",
            )

        (
            discovery_block_message,
            discovery_analysis,
            _planning_state,
        ) = await build_discovery_block_message_runtime(
            conversation,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            tenant_id=self.user.tenant_id,
        )
        if discovery_block_message is not None:
            return ToolProcessingResult(
                feedback=discovery_block_message,
                failure_kind="validation",
            )

        merged_assumptions = list(
            dict.fromkeys(
                [
                    *discovery_analysis.assumptions,
                    *requirements_data.get("assumptions", []),
                ]
            )
        )
        requirements_data["assumptions"] = merged_assumptions
        requirements_data = normalize_requirements_summary_for_flow(
            requirements_data,
            conversation=conversation,
            flow=flow,
            language=resolve_ui_language(conversation),
        )

        requirements_payload_model = RequirementsSummaryPayload.model_validate(
            requirements_data
        )
        requirements_version = build_requirements_version(requirements_payload_model)
        requirements_payload = {
            **requirements_data,
            "requirements_version": requirements_version,
        }

        tool_call = build_persisted_tool_call_stub(
            tool_call_id=tool_call_id,
            tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
        )
        new_version = await persist_tool_turn(
            repo=self.repo,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            tool_call=tool_call,
            arguments=arguments,
            tool_content="Requirements presented to user. Awaiting confirmation.",
            metadata={
                "requirements_summary": requirements_payload,
                "requirements_version": requirements_version,
            },
            assistant_metadata=assistant_metadata,
            flow=flow,
        )
        return ToolProcessingResult(
            event=build_requirements_summary_event(requirements_payload),
            new_planning_state_version=new_version,
        )

    async def _handle_confirm_requirements(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"Invalid requirements summary: {error}",
                tool_call=tool_call,
                retry_config=self._confirm_requirements_retry_config(ctx),
            ):
                yield event
            return

        confirm_result = await self._process_confirm_requirements_arguments(
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=arguments,
            assistant_content=ctx.text_content or "",
            assistant_metadata=_assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
                tool_calls=[tool_call],
            ),
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
        )
        if confirm_result.event is None:
            if confirm_result.failure_kind == "validation":
                followup_result = await self.emit_discovery_followup_if_needed(
                    turn=ctx.turn,
                    conversation=ctx.conversation,
                    new_messages_start=ctx.new_messages_start,
                    flow=ctx.flow,
                    litellm_model=ctx.litellm_model,
                    litellm_kwargs=ctx.litellm_kwargs,
                    assistant_metadata=_assistant_metadata_with_usage(
                        conversation=ctx.conversation,
                        base_metadata=ctx.assistant_metadata,
                        usage_tracker=ctx.usage_tracker,
                        tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                    ),
                )
                if followup_result is not None:
                    for event in followup_result.events:
                        yield event
                    return

            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=confirm_result.feedback
                or "Invalid requirements summary.",
                tool_call=tool_call,
                retry_config=self._confirm_requirements_retry_config(ctx),
            ):
                yield event
            return

        yield confirm_result.event

    async def _handle_edit_flow(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        try:
            raw_args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            _record_proposal_first_attempt(
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
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"Invalid edit_flow arguments: {error}",
                tool_call=tool_call,
                retry_config=edit_flow_retry_config(
                    processor=self,
                    assistant_snapshots=ctx.assistant_snapshots,
                    litellm_model=ctx.litellm_model,
                    litellm_kwargs=ctx.litellm_kwargs,
                    max_output_tokens=ctx.max_output_tokens,
                    plan_edit_context=ctx.plan_edit_context,
                    prior_plan_for_revision=ctx.prior_plan_for_revision,
                ),
            ):
                yield event
            return

        def _record_successful_proposal() -> None:
            _record_proposal_first_attempt(
                ctx.usage_tracker,
                request_id=ctx.request_id,
                tool_name=EDIT_FLOW_TOOL_NAME,
                success=True,
            )

        def _build_assistant_metadata() -> dict[str, Any] | None:
            return _assistant_metadata_with_usage(
                conversation=ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                usage_tracker=ctx.usage_tracker,
                tool_calls=[tool_call],
            )

        edit_result = await process_edit_arguments(
            processor=self,
            turn=ctx.turn,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=raw_args,
            assistant_content=ctx.text_content or "",
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            flow=ctx.flow,
            assistant_snapshots=ctx.assistant_snapshots,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            max_output_tokens=ctx.max_output_tokens,
            assistant_metadata=None,
            assistant_metadata_builder=_build_assistant_metadata,
            proposal_success_recorder=_record_successful_proposal,
            resource_catalog=ctx.resource_catalog,
            plan_edit_context=ctx.plan_edit_context,
            prior_plan_for_revision=ctx.prior_plan_for_revision,
        )
        if edit_result.event is None:
            proposal_repair_reason = proposal_repair_reason_from_tool_failure(
                edit_result.failure_kind
            )
            _record_proposal_first_attempt(
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
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=edit_result.feedback or "Invalid edit_flow arguments.",
                tool_call=tool_call,
                retry_config=edit_flow_retry_config(
                    processor=self,
                    assistant_snapshots=ctx.assistant_snapshots,
                    litellm_model=ctx.litellm_model,
                    litellm_kwargs=ctx.litellm_kwargs,
                    max_output_tokens=ctx.max_output_tokens,
                    plan_edit_context=ctx.plan_edit_context,
                    prior_plan_for_revision=ctx.prior_plan_for_revision,
                ),
            ):
                yield event
            return

        _record_successful_proposal()
        yield edit_result.event

    async def emit_discovery_followup_if_needed(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        litellm_model: str | None = None,
        litellm_kwargs: dict[str, Any] | None = None,
        ui_language: str | None = None,
        flow: "Flow | None" = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> BackendQuestionPersistenceResult | None:
        return await emit_discovery_followup_if_needed(
            repo=self.repo,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            ui_language=ui_language,
            assistant_metadata=assistant_metadata,
        )

    def _submission_retry_config(
        self,
        *,
        flow: "Flow | None",
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        planning_state: PlanningState | None = None,
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
    ) -> ToolRetryConfig:
        if flow is None:
            return outline_flow_retry_config(
                processor=self,
                planning_state=planning_state,
                plan_edit_context=plan_edit_context,
                prior_plan_for_revision=prior_plan_for_revision,
            )

        return edit_flow_retry_config(
            processor=self,
            assistant_snapshots=assistant_snapshots,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
        )

    def _confirm_requirements_retry_config(
        self, ctx: ProposalContext
    ) -> ToolRetryConfig:
        async def _process_tool_invocation(
            invocation: ToolRetryInvocation,
        ) -> ToolProcessingResult:
            return await self._process_confirm_requirements_arguments(
                turn=invocation.turn,
                conversation=invocation.conversation,
                new_messages_start=invocation.new_messages_start,
                arguments=invocation.arguments,
                assistant_content=invocation.assistant_content,
                assistant_metadata=invocation.assistant_metadata,
                tool_call_id=invocation.tool_call_id,
                available_model_refs=invocation.available_model_refs,
                available_kb_refs=invocation.available_kb_refs,
                flow=invocation.flow,
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
            )

        return ToolRetryConfig(
            target_tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
            forced_tool_prompt=(
                "Return one valid confirm_requirements tool call. "
                "Do not answer with prose."
            ),
            process_tool_invocation=_process_tool_invocation,
        )


def _active_submission_tool_name(flow: "Flow | None") -> str:
    return EDIT_FLOW_TOOL_NAME if flow is not None else OUTLINE_FLOW_TOOL_NAME


def _active_submission_tool_schemas(
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
