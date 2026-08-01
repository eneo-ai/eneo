from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, AsyncGenerator, assert_never
from uuid import UUID

from pydantic import ValidationError

from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context_for_model,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    AIBuilderQuestionAnswerInput,
    metadata_for_user_message,
    metadata_with_slot_classification,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import (
    build_committed_turn_replay_events,
    build_done_event,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    resolve_plan_edit_context,
)
from eneo.flows.ai_builder.ai_builder_plan_lifecycle import (
    raise_persisted_flow_mcp_plan_error,
)
from eneo.flows.ai_builder.ai_builder_planner_failure_events import (
    build_session_send_lease_lost_event,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    build_proposal_prepared,
    prepare_planner_request,
    validate_preprovider_output_schema_gate,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from eneo.flows.ai_builder.ai_builder_scoped_plan_revision import (
    ScopedPlanRevisionRequest,
    run_scoped_plan_revision_attempt,
)
from eneo.flows.ai_builder.ai_builder_send_lease import claim_ai_builder_send_turn
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionTelemetry,
    dispatch_server_decision,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionTurnAcceptance,
    SessionTurnPreflight,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import PlanningStatePayloadTooLargeError
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    resolve_flow_mapped_execution_policy,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_defaults import lookup_model_defaults

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
    from eneo.flows.domain.flow import Flow
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


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
        quality_retry_warning_code_set = frozenset(quality_retry_warning_codes)
        self._compiled_proposal_finalizer = CompiledProposalFinalizer(
            repo=repo,
            quality_retry_warning_codes=quality_retry_warning_code_set,
        )
        self._proposal_submission = ProposalSubmissionOwner(
            repo=repo,
            litellm_client=litellm_client,
            self_correction_temperature=self_correction_temperature,
            self_correction_bumped_temperature=self_correction_bumped_temperature,
            forced_proposal_temperature=forced_proposal_temperature,
            quality_retry_warning_codes=quality_retry_warning_code_set,
            compiled_proposal_finalizer=self._compiled_proposal_finalizer,
        )

    async def _complete_known_provider_rejection(
        self,
        *,
        turn: "SessionSendTurn",
        error: AIBuilderKnownProviderRejectionException,
    ) -> AIBuilderErrorEvent:
        await self.repo.complete_session_turn(turn=turn, error=error.public_error)
        return AIBuilderErrorEvent(data=error.public_error)

    async def _complete_planning_state_payload_too_large(
        self,
        *,
        turn: "SessionSendTurn",
        error: PlanningStatePayloadTooLargeError,
        request_id: str,
    ) -> AIBuilderErrorEvent:
        event = build_ai_builder_error_event(
            message="The AI Builder planning state is too large to save.",
            code=AIBuilderErrorCode.PLANNING_STATE_PAYLOAD_TOO_LARGE,
            phase=AIBuilderErrorPhase.PLANNER,
            request_id=request_id,
            details={
                "payload_bytes": error.byte_size,
                "payload_cap_bytes": error.cap_bytes,
            },
        )
        await self.repo.complete_session_turn(turn=turn, error=event.data)
        return event

    async def _stream_proposal_events(
        self,
        *,
        turn: "SessionSendTurn",
        conversation: list[ConversationMessage],
        new_messages_start: int,
        proposal_request: ProposalPrepared,
        completion_model_route: ResolvedCompletionModelRoute,
        max_output_tokens: int,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry,
        flow: "Flow | None",
        assistant_snapshots: AssistantAuthoringSnapshots | None,
        before_provider_call: Callable[[], Awaitable[None]],
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        try:
            events: list[AIBuilderStreamEvent] | None = None
            assistant_metadata = build_assistant_message_metadata(conversation)
            if flow is None:
                scoped_revision_result = await run_scoped_plan_revision_attempt(
                    request=ScopedPlanRevisionRequest(
                        turn=turn,
                        conversation=conversation,
                        new_messages_start=new_messages_start,
                        available_model_refs=proposal_request.resource_catalog.model_refs,
                        available_kb_refs=(
                            proposal_request.resource_catalog.knowledge_base_refs
                        ),
                        resource_catalog=proposal_request.resource_catalog,
                        plan_edit_context=proposal_request.plan_edit_context,
                        prior_plan_for_revision=proposal_request.prior_plan_for_revision,
                        request_id=request_id,
                        usage_tracker=usage_tracker,
                        requested_output_sections=(
                            proposal_request.requested_output_sections
                        ),
                        assistant_metadata=assistant_metadata,
                        flow=flow,
                    ),
                    finalizer=self._compiled_proposal_finalizer,
                )
                if scoped_revision_result is not None:
                    events = list(scoped_revision_result.events)

            if events is None:
                events = [
                    event
                    async for event in self._proposal_submission.run_active_submission_attempt(
                        turn=turn,
                        conversation=conversation,
                        new_messages_start=new_messages_start,
                        message_groups=proposal_request.message_groups,
                        completion_model_route=completion_model_route,
                        available_model_refs=proposal_request.resource_catalog.model_refs,
                        available_kb_refs=(
                            proposal_request.resource_catalog.knowledge_base_refs
                        ),
                        resource_catalog=proposal_request.resource_catalog,
                        max_output_tokens=max_output_tokens,
                        proposal_temperature=self.planner_temperature,
                        request_id=request_id,
                        usage_tracker=usage_tracker,
                        flow=flow,
                        assistant_snapshots=assistant_snapshots,
                        assistant_metadata=assistant_metadata,
                        planning_state=proposal_request.planning_state,
                        requested_output_sections=(
                            proposal_request.requested_output_sections
                        ),
                        plan_edit_context=proposal_request.plan_edit_context,
                        prior_plan_for_revision=proposal_request.prior_plan_for_revision,
                        before_provider_call=before_provider_call,
                        proposal_request_budget=(
                            replace(
                                proposal_request.request_budget,
                                request_id=request_id,
                            )
                            if proposal_request.request_budget is not None
                            else None
                        ),
                    )
                ]
        except PlanningStatePayloadTooLargeError as error:
            yield await self._complete_planning_state_payload_too_large(
                turn=turn,
                error=error,
                request_id=request_id,
            )
            return
        except AIBuilderKnownProviderRejectionException as error:
            yield await self._complete_known_provider_rejection(turn=turn, error=error)
            return
        error = next(
            (event.data for event in events if isinstance(event, AIBuilderErrorEvent)),
            None,
        )
        await self.repo.complete_session_turn(turn=turn, error=error)
        for event in events:
            yield event

    async def send_message(
        self,
        *,
        session_id: UUID,
        client_turn_id: UUID,
        request_fingerprint: str,
        request_snapshot: FlowPersistedJsonObject,
        acknowledge_duplicate_provider_spend: bool = False,
        message: str,
        file_ids: list[UUID] | None = None,
        question_answer: AIBuilderQuestionAnswerInput | None = None,
        edit_context: AIBuilderPlanEditContext | None = None,
        ui_language: str | None = None,
        completion_model_route: ResolvedCompletionModelRoute,
        available_models: list[AIBuilderAvailableModelResource] | None = None,
        available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
        attachment_context_policy: AIBuilderAttachmentContextPolicy | None = None,
        mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
        turn_preflight: SessionTurnPreflight | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        if turn_preflight is None:
            turn_preflight = await self.repo.preflight_session_turn(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                client_turn_id=client_turn_id,
                request_fingerprint=request_fingerprint,
                acknowledge_duplicate_provider_spend=(
                    acknowledge_duplicate_provider_spend
                ),
            )
        if turn_preflight.replayed:
            latest_turn = turn_preflight.session.latest_turn
            replay_error = latest_turn.error if latest_turn is not None else None
            for event in build_committed_turn_replay_events(replay_error):
                yield event
            return

        if budget_policy is None:
            budget_policy = resolve_ai_builder_budget_policy(None)
        if attachment_context_policy is None:
            attachment_context_policy = AIBuilderAttachmentContextPolicy(
                max_template_uncompressed_bytes=(
                    budget_policy.max_template_inspection_uncompressed_bytes
                ),
                max_template_placeholders=budget_policy.max_template_placeholders,
            )
        if mapped_execution_policy is None:
            mapped_execution_policy = resolve_flow_mapped_execution_policy(None)
        litellm_model = completion_model_route.litellm_model
        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)
        if max_input_tokens is None:
            max_input_tokens = defaults.max_input_tokens if defaults else None
        if max_output_tokens is None:
            max_output_tokens = defaults.max_output_tokens if defaults else None
        if max_input_tokens is None or max_output_tokens is None:
            raise AIBuilderBadRequestException(
                "AI Builder planner budget settings are missing.",
                code=AIBuilderErrorCode.PLANNER_BUDGET_MISSING,
            )

        session = turn_preflight.session
        session_status = _session_status_value(session.status)
        conversation = list(session.conversation)
        try:
            (
                plan_edit_context,
                prior_plan_for_revision,
            ) = await resolve_plan_edit_context(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session=session,
                context=edit_context,
            )
        except ValidationError as exc:
            raise_persisted_flow_mcp_plan_error(exc)
            raise
        prepared_metadata = prepare_user_question_metadata(
            conversation=conversation,
            message=message,
            question_answer=question_answer,
            ui_language=ui_language,
        )
        initial_metadata = prepared_metadata.metadata
        if plan_edit_context is not None:
            initial_metadata = {
                **(initial_metadata or {}),
                **(metadata_for_user_message(edit_context=plan_edit_context) or {}),
            }
        user_message_metadata = (
            {
                **(initial_metadata or {}),
                **(metadata_for_user_message(file_ids=file_ids) or {}),
            }
            if initial_metadata or file_ids
            else None
        )
        user_message = ConversationMessage(
            role="user",
            content=message,
            metadata=user_message_metadata,
        )
        async with claim_ai_builder_send_turn(
            repo=self.repo,
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            accepted_turn=SessionTurnAcceptance(
                client_turn_id=client_turn_id,
                request_fingerprint=request_fingerprint,
                request=request_snapshot,
                user_message=user_message,
                file_ids=tuple(file_ids or ()),
                acknowledge_duplicate_provider_spend=(
                    acknowledge_duplicate_provider_spend
                ),
            ),
            preparation_baseline=turn_preflight.baseline,
        ) as claimed_turn:
            if claimed_turn.replayed:
                for event in build_committed_turn_replay_events(
                    claimed_turn.committed_error
                ):
                    yield event
                return

            turn = claimed_turn.turn
            lease = turn.lease
            request_id = str(lease.request_id)
            usage_tracker = ProposalTurnTelemetry(
                request_id=request_id,
                model=completion_model_route.litellm_model,
                target_kind=TargetKind.EDIT if flow is not None else TargetKind.CREATE,
            )
            lease_lost_event = claimed_turn.lease_lost_event
            accepted_message = claimed_turn.user_message
            accepted_session = await self.repo.get_session(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
            )
            conversation = list(accepted_session.conversation)
            new_messages_start = next(
                index
                for index, persisted_message in enumerate(conversation)
                if persisted_message.message_id == accepted_message.message_id
            )
            user_message = conversation[new_messages_start]

            async def mark_provider_work_started() -> None:
                await self.repo.mark_session_turn_processing(turn=turn)

            if session_status == SessionStatus.AWAITING_APPROVAL.value:
                await self.repo.update_session_status(
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                    status=SessionStatus.CHATTING,
                    lease=lease,
                )

            persisted_planning_state = await self.repo.load_planning_state(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
            )
            prepared_attachment_context = build_ai_builder_attachment_context_for_model(
                attachment_files or [],
                policy=attachment_context_policy,
                model_name=litellm_model,
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                safety_buffer_tokens=(budget_policy.conversation_safety_buffer_tokens),
                minimum_conversation_tokens=(
                    budget_policy.minimum_conversation_budget_tokens
                ),
            )
            validate_preprovider_output_schema_gate(
                conversation=conversation,
                attachment_context=prepared_attachment_context,
            )
            metadata = prepared_metadata.metadata
            if plan_edit_context is not None:
                metadata = {
                    **(metadata or {}),
                    **(metadata_for_user_message(edit_context=plan_edit_context) or {}),
                }
            user_message.metadata = (
                {
                    **(metadata or {}),
                    **(metadata_for_user_message(file_ids=file_ids) or {}),
                }
                if metadata or file_ids
                else None
            )
            try:
                prepared_request = await prepare_planner_request(
                    PlannerRequestPreparationInput(
                        conversation=conversation,
                        litellm_client=self.litellm_client,
                        completion_model_route=completion_model_route,
                        available_models=available_models,
                        available_kbs=available_kbs,
                        flow=flow,
                        assistant_snapshots=assistant_snapshots,
                        attachment_files=attachment_files or [],
                        max_input_tokens=max_input_tokens,
                        max_output_tokens=max_output_tokens,
                        budget_policy=budget_policy,
                        attachment_context_policy=attachment_context_policy,
                        mapped_execution_policy=mapped_execution_policy,
                        plan_edit_context=plan_edit_context,
                        prior_plan_for_revision=prior_plan_for_revision,
                        persisted_planning_state=persisted_planning_state,
                        base_planning_state_version=turn.base_planning_state_version,
                        tenant_id=self.user.tenant_id,
                        current_turn_start=new_messages_start,
                        usage_tracker=usage_tracker,
                        before_provider_call=mark_provider_work_started,
                        prepared_attachment_context=prepared_attachment_context,
                        output_schema_gate_checked=True,
                    )
                )
            except AIBuilderKnownProviderRejectionException as error:
                yield await self._complete_known_provider_rejection(
                    turn=turn,
                    error=error,
                )
                yield build_done_event()
                return
            requirements_state = prepared_request.requirements_state
            ui_language = prepared_request.ui_language
            user_message.metadata = metadata_with_slot_classification(
                user_message.metadata,
                prepared_request.slot_classification_metadata,
            )
            await self.repo.append_session_messages(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                conversation=[user_message],
                lease=lease,
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
                        completion_model_route=completion_model_route,
                        max_output_tokens=max_output_tokens,
                        request_id=request_id,
                        usage_tracker=usage_tracker,
                        flow=flow,
                        assistant_snapshots=assistant_snapshots,
                        before_provider_call=mark_provider_work_started,
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
                                confirmed_attachment_evidence_fingerprint=(
                                    requirements_state.confirmed_attachment_evidence_fingerprint
                                ),
                                ui_language=ui_language,
                                telemetry=ServerDecisionTelemetry(
                                    request_id=request_id,
                                    litellm_model=litellm_model,
                                    usage_tracker=usage_tracker,
                                ),
                                planning_state=planner_turn_request.planning_state,
                                discovery_assumptions=(
                                    planner_turn_request.discovery_analysis.assumptions
                                ),
                            )
                        )
                    except PlanningStatePayloadTooLargeError as error:
                        yield await self._complete_planning_state_payload_too_large(
                            turn=turn,
                            error=error,
                            request_id=request_id,
                        )
                        yield build_done_event()
                        return
                    except AIBuilderBadRequestException as error:
                        if error.code is AIBuilderErrorCode.SESSION_SEND_LEASE_LOST:
                            yield build_session_send_lease_lost_event(
                                request_id=request_id
                            )
                            yield build_done_event()
                            return
                        raise
                    if lease_lost_event.is_set():
                        yield build_session_send_lease_lost_event(request_id=request_id)
                        yield build_done_event()
                        return

                    pending_events = list(dispatch_result.events)
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
                            current_steps=(None if flow is None else list(flow.steps)),
                            plan_edit_context=plan_edit_context,
                            prior_plan_for_revision=prior_plan_for_revision,
                            litellm_model=litellm_model,
                            max_input_tokens=max_input_tokens,
                            max_output_tokens=max_output_tokens,
                            budget_policy=budget_policy,
                            attachment_file_count=len(attachment_files or []),
                            current_turn_start=new_messages_start,
                        )
                        pending_events.extend(
                            [
                                event
                                async for event in self._stream_proposal_events(
                                    turn=continuation_turn,
                                    conversation=conversation,
                                    new_messages_start=len(conversation),
                                    proposal_request=proposal_request,
                                    completion_model_route=completion_model_route,
                                    max_output_tokens=max_output_tokens,
                                    request_id=request_id,
                                    usage_tracker=usage_tracker,
                                    flow=flow,
                                    assistant_snapshots=assistant_snapshots,
                                    before_provider_call=mark_provider_work_started,
                                )
                            ]
                        )
                    else:
                        error = next(
                            (
                                event.data
                                for event in pending_events
                                if isinstance(event, AIBuilderErrorEvent)
                            ),
                            None,
                        )
                        await self.repo.complete_session_turn(
                            turn=turn,
                            error=error,
                        )
                    for event in pending_events:
                        yield event
                    yield build_done_event()
                    return
                case _:
                    assert_never(prepared_request)
