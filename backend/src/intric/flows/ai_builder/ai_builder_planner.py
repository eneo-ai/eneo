from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, AsyncGenerator, assert_never
from uuid import UUID, uuid4

from intric.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    unsupported_structured_output_decision,
)
from intric.files.file_models import File
from intric.flows.ai_builder.ai_builder_accepted_action_rendering import (
    RequirementsSummaryRenderContext,
    build_accepted_action_messages,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    UI_LANGUAGE_METADATA_KEY,
    AIBuilderQuestionAnswerInput,
    metadata_for_user_message,
    metadata_with_slot_classification,
    requirements_confirmation_from_question_answer,
    ui_language_from_question_answer,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    infer_question_answer_from_freeform,
    latest_pending_structured_question,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    PlannerOutput,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    resolve_plan_edit_context,
)
from intric.flows.ai_builder.ai_builder_planner_action_dispatch import (
    BackendSelectedQuestionDispatchRequest,
    DispatchedActionEventRequest,
    build_dispatched_action_events,
    dispatch_backend_selected_question_if_any,
)
from intric.flows.ai_builder.ai_builder_planner_failure_events import (
    PlannerTurnResultEventRequest,
    build_planner_turn_error_event,
    build_planner_upstream_error_event,
    build_session_send_lease_lost_event,
    record_planner_turn_result,
)
from intric.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    prepare_planner_request,
)
from intric.flows.ai_builder.ai_builder_planner_turn import (
    build_planner_litellm_kwargs,
    run_planner_turn,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from intric.flows.ai_builder.ai_builder_response_format import (
    build_planner_request_response_format,
)
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.model_providers.domain.model_defaults import lookup_model_defaults

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)

_MESSAGE_ACCEPTING_SESSION_STATUSES = {
    SessionStatus.CHATTING.value,
    SessionStatus.AWAITING_APPROVAL.value,
}


def _session_status_value(status: object) -> str:
    value = getattr(status, "value", None)
    if isinstance(value, str):
        return value
    return str(status)


@dataclass(frozen=True)
class PlannerMetadataResolution:
    metadata: dict[str, Any] | None
    is_requirements_confirmation: bool
    used_auxiliary_llm: bool


def _default_structured_output_decision() -> StructuredOutputCapabilityDecision:
    return unsupported_structured_output_decision()


class AIBuilderPlanner:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        discovery_temperature: float = 0.6,
        planner_temperature: float = 0.4,
        self_correction_temperature: float = 0.35,
        self_correction_bumped_temperature: float = 0.6,
        forced_proposal_temperature: float = 0.1,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.discovery_temperature = discovery_temperature
        self.planner_temperature = planner_temperature
        self.proposal_processor = AIBuilderProposalProcessor(
            user=user,
            repo=repo,
            litellm_client=litellm_client,
            self_correction_temperature=self_correction_temperature,
            self_correction_bumped_temperature=self_correction_bumped_temperature,
            forced_proposal_temperature=forced_proposal_temperature,
            quality_retry_warning_codes=quality_retry_warning_codes,
        )

    @staticmethod
    def _send_lock_lease_seconds() -> int:
        return max(30, int(get_settings().ai_builder_send_lock_lease_seconds))

    @classmethod
    def _next_send_lock_expiry(cls) -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            seconds=cls._send_lock_lease_seconds()
        )

    @classmethod
    def _send_lock_refresh_interval_seconds(cls) -> int:
        return max(5, cls._send_lock_lease_seconds() // 3)

    async def _maintain_send_lock_lease(
        self,
        *,
        session_id: UUID,
        lease: SessionSendLease,
        stop_event: asyncio.Event,
        lease_lost_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._send_lock_refresh_interval_seconds(),
                )
                return
            except asyncio.TimeoutError:
                try:
                    refreshed = await self.repo.refresh_session_send_lease(
                        session_id=session_id,
                        tenant_id=self.user.tenant_id,
                        lease=lease,
                        lock_expires_at=self._next_send_lock_expiry(),
                    )
                except Exception as error:
                    logger.warning(
                        "AI Builder send lease refresh failed.",
                        exc_info=error,
                        extra={
                            "session_id": str(session_id),
                            "request_id": str(lease.request_id),
                        },
                    )
                    lease_lost_event.set()
                    return

                if not refreshed:
                    logger.warning(
                        "AI Builder send lease lost while processing.",
                        extra={
                            "session_id": str(session_id),
                            "request_id": str(lease.request_id),
                        },
                    )
                    lease_lost_event.set()
                    return

    async def _resolve_message_metadata(
        self,
        *,
        conversation: list[ConversationMessage],
        message: str,
        question_answer: AIBuilderQuestionAnswerInput | None,
        ui_language: str | None = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
    ) -> PlannerMetadataResolution:
        if ui_language is None and question_answer is not None:
            ui_language = ui_language_from_question_answer(question_answer)

        is_requirements_confirmation = (
            requirements_confirmation_from_question_answer(question_answer) is not None
        )
        metadata: dict[str, Any] | None = None
        if question_answer is not None:
            metadata = metadata_for_user_message(question_answer=question_answer)

        used_auxiliary_llm = False
        if metadata is None and not is_requirements_confirmation:
            inferred_answer = infer_question_answer_from_freeform(conversation, message)
            if inferred_answer is not None:
                metadata = metadata_for_user_message(question_answer=inferred_answer)
            elif latest_pending_structured_question(conversation) is not None:
                adjudicated_answer = await adjudicate_pending_question_answer(
                    litellm_client=self.litellm_client,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    conversation=conversation,
                    user_message=message,
                )
                if adjudicated_answer is not None:
                    metadata = metadata_for_user_message(
                        question_answer=adjudicated_answer.to_question_answer()
                    )
                used_auxiliary_llm = True

        if ui_language is not None:
            metadata = {
                **(metadata or {}),
                UI_LANGUAGE_METADATA_KEY: ui_language,
            }

        return PlannerMetadataResolution(
            metadata=metadata,
            is_requirements_confirmation=is_requirements_confirmation,
            used_auxiliary_llm=used_auxiliary_llm,
        )

    async def send_message(
        self,
        *,
        session_id: UUID,
        message: str,
        file_ids: list[UUID] | None = None,
        question_answer: AIBuilderQuestionAnswerInput | None = None,
        edit_context: AIBuilderPlanEditContext | None = None,
        ui_language: str | None = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        structured_output_decision: StructuredOutputCapabilityDecision | None = None,
        available_models: list[AIBuilderAvailableModelResource] | None = None,
        available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
        available_mcps: AIBuilderMCPResourceInput = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        if budget_policy is None:
            budget_policy = resolve_ai_builder_budget_policy(None)

        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)

        if max_input_tokens is None:
            max_input_tokens = (
                defaults.max_input_tokens if defaults else None
            ) or budget_policy.unknown_model_context_window_tokens
        if max_output_tokens is None:
            max_output_tokens = defaults.max_output_tokens if defaults else None

        if max_input_tokens is None or max_output_tokens is None:
            raise AIBuilderBadRequestException(
                "AI Builder planner budget settings are missing.",
                code=AIBuilderErrorCode.PLANNER_BUDGET_MISSING,
            )

        response_format_selection = build_planner_request_response_format(
            structured_output_decision or _default_structured_output_decision()
        )

        session = await self.repo.get_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        session_status = _session_status_value(session.status)
        if session_status not in _MESSAGE_ACCEPTING_SESSION_STATUSES:
            raise AIBuilderBadRequestException(
                f"Cannot send messages in session status '{session_status}'.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )

        request_id = str(uuid4())
        request_uuid = UUID(request_id)
        lock_token = uuid4()
        lease = SessionSendLease(request_id=request_uuid, lock_token=lock_token)
        turn = SessionSendTurn(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            lease=lease,
            base_planning_state_version=session.planning_state_version,
        )
        lease_stop_event = asyncio.Event()
        lease_lost_event = asyncio.Event()
        claimed = await self.repo.claim_session_send(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            lease=lease,
            lock_expires_at=self._next_send_lock_expiry(),
        )
        if not claimed:
            raise AIBuilderBadRequestException(
                "Another AI Builder message is already being processed for this session.",
                code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
            )
        lease_task = asyncio.create_task(
            self._maintain_send_lock_lease(
                session_id=session_id,
                lease=lease,
                stop_event=lease_stop_event,
                lease_lost_event=lease_lost_event,
            )
        )

        try:
            if session_status == SessionStatus.AWAITING_APPROVAL.value:
                await self.repo.update_session_status(
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                    status=SessionStatus.CHATTING,
                    lease=lease,
                )

            conversation = list(session.conversation)
            (
                plan_edit_context,
                prior_plan_for_revision,
            ) = await resolve_plan_edit_context(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session=session,
                context=edit_context,
            )
            persisted_planning_state = await self.repo.load_planning_state(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
            )
            metadata_resolution = await self._resolve_message_metadata(
                conversation=conversation,
                message=message,
                question_answer=question_answer,
                ui_language=ui_language,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
            )
            metadata = metadata_resolution.metadata
            if plan_edit_context is not None:
                metadata = {
                    **(metadata or {}),
                    **(metadata_for_user_message(edit_context=plan_edit_context) or {}),
                }
            is_requirements_confirmation = (
                metadata_resolution.is_requirements_confirmation
            )

            user_message = ConversationMessage(
                role="user",
                content=message,
                metadata=(
                    {
                        **(metadata or {}),
                        **(metadata_for_user_message(file_ids=file_ids) or {}),
                    }
                    if metadata or file_ids
                    else None
                ),
            )
            new_messages_start = len(conversation)
            conversation.append(user_message)
            prepared_request = await prepare_planner_request(
                PlannerRequestPreparationInput(
                    conversation=conversation,
                    message=message,
                    litellm_client=self.litellm_client,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    available_models=available_models,
                    available_kbs=available_kbs,
                    available_mcps=available_mcps,
                    flow=flow,
                    assistant_snapshots=assistant_snapshots,
                    attachment_files=attachment_files or [],
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=max_output_tokens,
                    budget_policy=budget_policy,
                    is_requirements_confirmation=is_requirements_confirmation,
                    plan_edit_context=plan_edit_context,
                    prior_plan_for_revision=prior_plan_for_revision,
                    allow_discovery_semantic_adjudication=(
                        not metadata_resolution.used_auxiliary_llm
                    ),
                    persisted_planning_state=persisted_planning_state,
                    base_planning_state_version=session.planning_state_version,
                    tenant_id=self.user.tenant_id,
                )
            )
            requirements_state = prepared_request.requirements_state
            ui_language = prepared_request.ui_language
            user_message.metadata = metadata_with_slot_classification(
                user_message.metadata,
                prepared_request.slot_classification_metadata,
            )

            precomputed_output: PlannerOutput | None
            planner_turn_messages: list[dict[str, Any]]
            planner_turn_context: OrchestrationContext
            planner_prompt_hash: str | None
            match prepared_request:
                case ProposalPrepared() as proposal_request:
                    async for event in self.proposal_processor.propose_plan(
                        turn=turn,
                        conversation=conversation,
                        new_messages_start=new_messages_start,
                        llm_messages=proposal_request.llm_messages,
                        litellm_model=litellm_model,
                        litellm_kwargs=litellm_kwargs,
                        available_model_refs=(
                            proposal_request.resource_catalog.model_refs
                        ),
                        available_kb_refs=(
                            proposal_request.resource_catalog.knowledge_base_refs
                        ),
                        resource_catalog=proposal_request.resource_catalog,
                        max_output_tokens=max_output_tokens,
                        proposal_temperature=self.planner_temperature,
                        request_id=request_id,
                        flow=flow,
                        assistant_snapshots=assistant_snapshots,
                        assistant_metadata=build_assistant_message_metadata(
                            conversation
                        ),
                        planning_state=(
                            proposal_request.orchestration_context.session_state
                        ),
                        discovery_runtime=proposal_request.discovery_runtime,
                        plan_edit_context=proposal_request.plan_edit_context,
                        prior_plan_for_revision=(
                            proposal_request.prior_plan_for_revision
                        ),
                    ):
                        yield event
                    yield {"event": SSE_EVENT_DONE, "data": ""}
                    return
                case ServerOutputPrepared() as planner_turn_request:
                    server_question_events = (
                        await dispatch_backend_selected_question_if_any(
                            BackendSelectedQuestionDispatchRequest(
                                repo=self.repo,
                                turn=turn,
                                server_output=planner_turn_request.server_output,
                                conversation=conversation,
                                new_messages_start=new_messages_start,
                                flow=flow,
                                discovery_analysis=(
                                    planner_turn_request.discovery_analysis
                                ),
                            )
                        )
                    )
                    if server_question_events is not None:
                        for event in server_question_events:
                            yield event
                        yield {"event": SSE_EVENT_DONE, "data": ""}
                        return
                    precomputed_output = planner_turn_request.server_output
                    planner_turn_messages = []
                    planner_turn_context = planner_turn_request.orchestration_context
                    planner_prompt_hash = None
                case _:
                    assert_never(prepared_request)

            render_context = RequirementsSummaryRenderContext(
                conversation=conversation,
                flow=flow,
                ui_language=ui_language,
            )

            try:
                turn_result = await run_planner_turn(
                    repo=self.repo,
                    litellm_client=self.litellm_client,
                    litellm_model=litellm_model,
                    litellm_kwargs=build_planner_litellm_kwargs(
                        litellm_kwargs=litellm_kwargs,
                        max_tokens=max_output_tokens,
                        temperature=(
                            self.discovery_temperature
                            if not requirements_state.confirmed
                            else self.planner_temperature
                        ),
                        response_format_selection=response_format_selection,
                    ),
                    turn=turn,
                    flow=flow,
                    base_messages=planner_turn_messages,
                    orchestration_context=planner_turn_context,
                    build_new_messages=partial(
                        build_accepted_action_messages,
                        context=render_context,
                        new_messages_start=new_messages_start,
                        used_auxiliary_llm=metadata_resolution.used_auxiliary_llm,
                    ),
                    precomputed_output=precomputed_output,
                )
            except AIBuilderBadRequestException as error:
                if error.code is AIBuilderErrorCode.SESSION_SEND_LEASE_LOST:
                    yield build_session_send_lease_lost_event(request_id=request_id)
                    yield {"event": SSE_EVENT_DONE, "data": ""}
                    return
                raise
            except Exception as error:
                logger.error(
                    "AI Builder planner turn failed",
                    exc_info=error,
                    extra={"request_id": request_id},
                )
                yield build_planner_upstream_error_event(request_id=request_id)
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            if lease_lost_event.is_set():
                yield build_session_send_lease_lost_event(request_id=request_id)
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            turn_event_request = PlannerTurnResultEventRequest(
                turn_result=turn_result,
                request_id=request_id,
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                planning_state_version=session.planning_state_version,
                planner_prompt_hash=planner_prompt_hash,
                response_format_selection=response_format_selection,
                max_output_tokens=max_output_tokens,
            )
            record_planner_turn_result(turn_event_request)

            error_event = build_planner_turn_error_event(turn_event_request)
            if error_event is not None:
                yield error_event
            elif turn_result.kind == "dispatched":
                events = await build_dispatched_action_events(
                    DispatchedActionEventRequest(
                        repo=self.repo,
                        litellm_client=self.litellm_client,
                        turn=turn,
                        turn_result=turn_result,
                        conversation=conversation,
                        litellm_model=litellm_model,
                        litellm_kwargs=litellm_kwargs,
                        response_format_selection=response_format_selection,
                        flow=flow,
                        requirements_confirmed=requirements_state.confirmed,
                        ui_language=ui_language,
                        planner_temperature=self.planner_temperature,
                    )
                )
                for event in events:
                    yield event

            yield {"event": SSE_EVENT_DONE, "data": ""}
        finally:
            lease_stop_event.set()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.warning(
                    "AI Builder lease task exited with an unexpected error.",
                    exc_info=error,
                    extra={"session_id": str(session_id), "request_id": request_id},
                )
            await self.repo.release_session_send(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                lease=lease,
            )
