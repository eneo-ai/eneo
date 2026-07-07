from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, AsyncGenerator, assert_never
from uuid import UUID

from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    AIBuilderQuestionAnswerInput,
    metadata_for_user_message,
    metadata_with_slot_classification,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import build_done_event
from eneo.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    resolve_plan_edit_context,
)
from eneo.flows.ai_builder.ai_builder_planner_failure_events import (
    build_planner_upstream_error_event,
    build_session_send_lease_lost_event,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    build_proposal_prepared,
    prepare_planner_request,
)
from eneo.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from eneo.flows.ai_builder.ai_builder_send_lease import claim_ai_builder_send_turn
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionTelemetry,
    dispatch_server_decision,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    resolve_user_question_metadata,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_defaults import lookup_model_defaults

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
    from eneo.flows.domain.flow import Flow
    from eneo.users.user import UserInDB

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


class AIBuilderPlanner:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        planner_temperature: float = 0.4,
        self_correction_temperature: float = 0.35,
        self_correction_bumped_temperature: float = 0.6,
        forced_proposal_temperature: float = 0.1,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
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

    async def _stream_proposal_events(
        self,
        *,
        turn: "SessionSendTurn",
        conversation: list[ConversationMessage],
        new_messages_start: int,
        proposal_request: ProposalPrepared,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        request_id: str,
        flow: "Flow | None",
        assistant_snapshots: AssistantAuthoringSnapshots | None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        async for event in self.proposal_processor.propose_plan(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=proposal_request.llm_messages,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=proposal_request.resource_catalog.model_refs,
            available_kb_refs=proposal_request.resource_catalog.knowledge_base_refs,
            resource_catalog=proposal_request.resource_catalog,
            max_output_tokens=max_output_tokens,
            proposal_temperature=self.planner_temperature,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=build_assistant_message_metadata(conversation),
            planning_state=proposal_request.planning_state,
            plan_edit_context=proposal_request.plan_edit_context,
            prior_plan_for_revision=proposal_request.prior_plan_for_revision,
        ):
            yield event

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
        available_models: list[AIBuilderAvailableModelResource] | None = None,
        available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
        available_mcps: AIBuilderMCPResourceInput = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
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

        async with claim_ai_builder_send_turn(
            repo=self.repo,
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            base_planning_state_version=session.planning_state_version,
        ) as claimed_turn:
            turn = claimed_turn.turn
            lease = turn.lease
            request_id = str(lease.request_id)
            lease_lost_event = claimed_turn.lease_lost_event

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
            metadata_resolution = await resolve_user_question_metadata(
                litellm_client=self.litellm_client,
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

            match prepared_request:
                case ProposalPrepared() as proposal_request:
                    # Preserve proposal/server refresh-signal asymmetry: proposal
                    # writes stay lease-guarded inside the processor.
                    async for event in self._stream_proposal_events(
                        turn=turn,
                        conversation=conversation,
                        new_messages_start=new_messages_start,
                        proposal_request=proposal_request,
                        litellm_model=litellm_model,
                        litellm_kwargs=litellm_kwargs,
                        max_output_tokens=max_output_tokens,
                        request_id=request_id,
                        flow=flow,
                        assistant_snapshots=assistant_snapshots,
                    ):
                        yield event
                    yield build_done_event()
                    return
                case ServerOutputPrepared() as planner_turn_request:
                    try:
                        dispatch_result = await dispatch_server_decision(
                            ServerDecisionDispatchRequest(
                                repo=self.repo,
                                turn=turn,
                                decision=planner_turn_request.server_decision,
                                conversation=conversation,
                                new_messages_start=new_messages_start,
                                flow=flow,
                                requirements_confirmed=requirements_state.confirmed,
                                ui_language=ui_language,
                                telemetry=ServerDecisionTelemetry(
                                    request_id=request_id,
                                    litellm_model=litellm_model,
                                    used_auxiliary_llm=(
                                        metadata_resolution.used_auxiliary_llm
                                    ),
                                ),
                                planning_state=planner_turn_request.planning_state,
                            )
                        )
                    except AIBuilderBadRequestException as error:
                        if error.code is AIBuilderErrorCode.SESSION_SEND_LEASE_LOST:
                            yield build_session_send_lease_lost_event(
                                request_id=request_id
                            )
                            yield build_done_event()
                            return
                        raise
                    except Exception as error:
                        logger.error(
                            "AI Builder server decision dispatch failed",
                            exc_info=error,
                            extra={"request_id": request_id},
                        )
                        yield build_planner_upstream_error_event(request_id=request_id)
                        yield build_done_event()
                        return

                    if lease_lost_event.is_set():
                        yield build_session_send_lease_lost_event(request_id=request_id)
                        yield build_done_event()
                        return

                    for event in dispatch_result.events:
                        yield event
                    if dispatch_result.proposal_continuation is not None:
                        continuation_turn = replace(
                            turn,
                            base_planning_state_version=(
                                dispatch_result.new_planning_state_version
                            ),
                        )
                        proposal_request = build_proposal_prepared(
                            requirements_state=requirements_state,
                            ui_language=ui_language,
                            slot_classification_metadata=(
                                planner_turn_request.slot_classification_metadata
                            ),
                            conversation=conversation,
                            planning_state=(
                                dispatch_result.proposal_continuation.planning_state
                            ),
                            attachment_context=planner_turn_request.attachment_context,
                            flow_context=planner_turn_request.flow_context,
                            is_edit_mode=flow is not None,
                            resource_catalog=planner_turn_request.resource_catalog,
                            plan_edit_context=plan_edit_context,
                            prior_plan_for_revision=prior_plan_for_revision,
                            litellm_model=litellm_model,
                            max_input_tokens=max_input_tokens,
                            max_output_tokens=max_output_tokens,
                            budget_policy=budget_policy,
                            attachment_file_count=len(attachment_files or []),
                        )
                        async for event in self._stream_proposal_events(
                            turn=continuation_turn,
                            conversation=conversation,
                            new_messages_start=len(conversation),
                            proposal_request=proposal_request,
                            litellm_model=litellm_model,
                            litellm_kwargs=litellm_kwargs,
                            max_output_tokens=max_output_tokens,
                            request_id=request_id,
                            flow=flow,
                            assistant_snapshots=assistant_snapshots,
                        ):
                            yield event
                    yield build_done_event()
                    return
                case _:
                    assert_never(prepared_request)
