from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
)

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    BackendQuestionPersistenceResult,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_confirm_requirements import (
    ConfirmRequirementsProcessingRequest,
    ConfirmRequirementsRetryConfigRequest,
    build_confirm_requirements_retry_config,
    process_confirm_requirements,
)
from intric.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from intric.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    make_usage_tracked_proposal_completion,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    build_mcp_resource_selection_question,
    find_named_mcp_request_issue,
    mcp_selection_answer_allows_planning,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    build_proposal_self_correction_request,
    run_tool_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalTurnContext,
)
from intric.flows.ai_builder.ai_builder_question_recovery import (
    RecoveredToolDispatchRequest,
    StructuredQuestionRecoveryRequest,
    stream_structured_question_tool_call,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)


def _conversation_user_text(conversation: list[ConversationMessage]) -> str:
    return "\n".join(
        message.content
        for message in conversation
        if message.role == "user" and message.content
    )


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
        proposal_submission: ProposalSubmissionOwner | None = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        if proposal_submission is None:
            proposal_submission = ProposalSubmissionOwner(
                repo=repo,
                litellm_client=litellm_client,
                self_correction_temperature=self_correction_temperature,
                self_correction_bumped_temperature=self_correction_bumped_temperature,
                forced_proposal_temperature=forced_proposal_temperature,
                quality_retry_warning_codes=frozenset(quality_retry_warning_codes),
            )
        self._proposal_submission = proposal_submission

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
        discovery_runtime: DiscoveryRuntimeResult | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
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
            text_content=text_content,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            usage_tracker=usage_tracker,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            discovery_runtime=discovery_runtime,
        )
        if (
            ctx.text_content
            and not self._proposal_submission.contains_submission_tool_call(tool_calls)
        ):
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
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
        discovery_runtime: DiscoveryRuntimeResult | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the server-selected plan proposal task.

        This is deliberately narrower than the planner contract: the
        server already selected `propose_plan`, so the model only fills
        the create/edit tool payload.
        """

        mcp_preflight_result = await self._mcp_preflight_events_if_needed(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            resource_catalog=resource_catalog,
            flow=flow,
            assistant_metadata=assistant_metadata,
        )
        if mcp_preflight_result is not None:
            for event in mcp_preflight_result.events:
                yield event
            return

        async for event in self._proposal_submission.run_active_submission_attempt(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            proposal_temperature=proposal_temperature,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            discovery_runtime=discovery_runtime,
        ):
            yield event

    def _dispatch_known_tool_call(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None] | None:
        tool_name = tool_call.function.name
        if tool_name == ASK_STRUCTURED_QUESTION_TOOL_NAME:
            return self._handle_question_recovery_dispatch(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == PROPOSE_FLOW_TOOL_NAME:
            return self._proposal_submission.dispatch_submission_tool_call(
                ctx=ctx, tool_call=tool_call
            )
        if tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME:
            return self._handle_confirm_requirements(
                ctx=ctx,
                tool_call=tool_call,
            )
        return None

    async def _handle_question_recovery_dispatch(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        request = StructuredQuestionRecoveryRequest(
            ctx=ctx,
            tool_call=tool_call,
        )
        async for item in stream_structured_question_tool_call(
            repo=self.repo,
            discovery_litellm_client=self.litellm_client,
            repair_completion=make_usage_tracked_proposal_completion(
                litellm_client=self.litellm_client,
                usage_tracker=ctx.usage_tracker,
            ),
            self_correction_temperature=self.self_correction_temperature,
            request=request,
        ):
            if isinstance(item, RecoveredToolDispatchRequest):
                async for event in self.handle_tool_call(
                    turn=ctx.turn,
                    conversation=ctx.conversation,
                    new_messages_start=ctx.new_messages_start,
                    tool_calls=item.tool_calls,
                    text_content=item.text_content,
                    llm_messages=item.llm_messages,
                    tool_schemas=item.tool_schemas,
                    litellm_model=ctx.litellm_model,
                    litellm_kwargs=ctx.litellm_kwargs,
                    available_model_refs=ctx.available_model_refs,
                    available_kb_refs=ctx.available_kb_refs,
                    resource_catalog=ctx.resource_catalog,
                    max_output_tokens=ctx.max_output_tokens,
                    request_id=item.request_id,
                    assistant_metadata=ctx.assistant_metadata,
                    flow=ctx.flow,
                    assistant_snapshots=ctx.assistant_snapshots,
                    planning_state=ctx.planning_state,
                    plan_edit_context=ctx.plan_edit_context,
                    prior_plan_for_revision=ctx.prior_plan_for_revision,
                    usage_tracker=ctx.usage_tracker,
                    discovery_runtime=ctx.discovery_runtime,
                ):
                    yield event
                return
            yield item

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
            question=BackendQuestion(
                question_data=question_data,
                assistant_text=assistant_text,
            ),
            assistant_metadata=assistant_metadata,
            tool_content=(
                "MCP selection question presented before proposal because the user "
                "requested an MCP by name and must choose from enabled space MCP resources."
            ),
            flow=flow,
        )

    async def _handle_confirm_requirements(
        self,
        *,
        ctx: ProposalTurnContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        retry_config = build_confirm_requirements_retry_config(
            ConfirmRequirementsRetryConfigRequest(
                repo=self.repo,
                litellm_client=self.litellm_client,
                tenant_id=self.user.tenant_id,
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
                target_kind=TargetKind.EDIT
                if ctx.flow is not None
                else TargetKind.CREATE,
            )
        )
        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError as error:
            async for event in run_tool_self_correction(
                build_proposal_self_correction_request(
                    ctx=ctx,
                    error_message=f"Invalid requirements summary: {error}",
                    tool_call=tool_call,
                    retry_config=retry_config,
                    self_correction_temperature=self.self_correction_temperature,
                    self_correction_bumped_temperature=(
                        self.self_correction_bumped_temperature
                    ),
                    forced_proposal_temperature=self.forced_proposal_temperature,
                    repair_completion=make_usage_tracked_proposal_completion(
                        litellm_client=self.litellm_client,
                        usage_tracker=ctx.usage_tracker,
                    ),
                )
            ):
                yield event
            return

        confirm_result = await process_confirm_requirements(
            ConfirmRequirementsProcessingRequest(
                repo=self.repo,
                turn=ctx.turn,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                arguments=arguments,
                tool_call_id=tool_call.id,
                flow=ctx.flow,
                litellm_client=self.litellm_client,
                litellm_model=ctx.litellm_model,
                litellm_kwargs=ctx.litellm_kwargs,
                tenant_id=self.user.tenant_id,
                assistant_metadata=assistant_metadata_with_usage(
                    conversation=ctx.conversation,
                    base_metadata=ctx.assistant_metadata,
                    usage_tracker=ctx.usage_tracker,
                    tool_calls=[tool_call],
                ),
                usage_tracker=ctx.usage_tracker,
                allow_discovery_followup=True,
                discovery_runtime=ctx.discovery_runtime,
            )
        )
        if confirm_result.has_events:
            for event in confirm_result.iter_events():
                yield event
            return

        async for event in run_tool_self_correction(
            build_proposal_self_correction_request(
                ctx=ctx,
                error_message=confirm_result.feedback
                or "Invalid requirements summary.",
                tool_call=tool_call,
                retry_config=retry_config,
                self_correction_temperature=self.self_correction_temperature,
                self_correction_bumped_temperature=(
                    self.self_correction_bumped_temperature
                ),
                forced_proposal_temperature=self.forced_proposal_temperature,
                repair_completion=make_usage_tracked_proposal_completion(
                    litellm_client=self.litellm_client,
                    usage_tracker=ctx.usage_tracker,
                ),
            )
        ):
            yield event
