from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, assert_never

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_summary_to_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStreamEvent,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_requirements_summary_event,
    build_status_event,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    normalize_requirements_summary_for_flow,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
    build_planner_telemetry,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    BuilderTurnDecision,
    CommitArchitecture,
    ConfirmRequirements,
    GenerateProposal,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)

ServerDecisionKind = Literal[
    "ask_question",
    "commit_architecture",
    "revise_architecture",
    "confirm_requirements",
]


@dataclass(frozen=True, slots=True)
class ServerDecisionTelemetry:
    request_id: str
    litellm_model: str
    used_auxiliary_llm: bool


@dataclass(frozen=True, slots=True)
class ServerDecisionDispatchRequest:
    repo: "AIBuilderRepository"
    turn: SessionSendTurn
    decision: BuilderTurnDecision
    conversation: list[ConversationMessage]
    new_messages_start: int
    flow: "Flow | None"
    requirements_confirmed: bool
    ui_language: str | None
    telemetry: ServerDecisionTelemetry
    planning_state: PlanningState


@dataclass(frozen=True, slots=True)
class ServerDecisionDispatchResult:
    action_kind: ServerDecisionKind
    events: tuple[AIBuilderStreamEvent, ...]
    new_planning_state_version: int
    proposal_continuation: ServerDecisionProposalContinuation | None = None


@dataclass(frozen=True, slots=True)
class ServerDecisionProposalContinuation:
    planning_state: PlanningState


async def dispatch_server_decision(
    request: ServerDecisionDispatchRequest,
) -> ServerDecisionDispatchResult:
    decision = request.decision
    match decision:
        case AskCanonicalQuestion():
            return await _dispatch_question(request, decision)
        case CommitArchitecture():
            return await _dispatch_architecture_commit(
                request,
                decision,
                action_kind="commit_architecture",
                status="architecture_committed",
            )
        case ReviseArchitecture():
            return await _dispatch_architecture_commit(
                request,
                decision,
                action_kind="revise_architecture",
                status="architecture_revised",
            )
        case ConfirmRequirements():
            return await _dispatch_requirements_confirmation(request, decision)
        case GenerateProposal() as unhandled:
            raise ValueError(
                "GenerateProposal must be routed to AIBuilderProposalProcessor, "
                f"not dispatch_server_decision: {unhandled!r}"
            )
        case _ as unhandled:
            assert_never(unhandled)


async def _dispatch_question(
    request: ServerDecisionDispatchRequest,
    decision: AskCanonicalQuestion,
) -> ServerDecisionDispatchResult:
    question_id = decision.slot_name
    followup = build_registry_question_followup(
        question_id,
        request.conversation,
        flow=request.flow,
    )

    telemetry = _server_turn_telemetry(
        request,
        action_kind="ask_question",
        architecture_commit_populated=False,
        tool_call_count=1 if followup is not None else 0,
    )
    if followup is not None:
        persisted = await persist_backend_question(
            repo=request.repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            question=followup,
            flow=request.flow,
            assistant_metadata=build_assistant_message_metadata(
                request.conversation,
                planner_telemetry=telemetry,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
            planning_state_overlay=request.planning_state,
        )
        return ServerDecisionDispatchResult(
            action_kind="ask_question",
            events=persisted.events,
            new_planning_state_version=persisted.new_planning_state_version,
        )

    logger.error(
        "AI Builder server question could not be rendered as a structured question.",
        extra={
            "question_id": question_id,
            "request_id": request.telemetry.request_id,
        },
    )
    return ServerDecisionDispatchResult(
        action_kind="ask_question",
        events=(
            build_ai_builder_error_event(
                message="The AI Builder could not render the next question.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.QUESTION,
                request_id=request.telemetry.request_id,
                diagnostic_context={"outcome_kind": "unrenderable_server_question"},
                details={"question_id": question_id},
            ),
        ),
        new_planning_state_version=request.turn.base_planning_state_version,
    )


async def _dispatch_architecture_commit(
    request: ServerDecisionDispatchRequest,
    decision: CommitArchitecture | ReviseArchitecture,
    *,
    action_kind: ServerDecisionKind,
    status: Literal["architecture_committed", "architecture_revised"],
) -> ServerDecisionDispatchResult:
    new_version = await request.repo.commit_turn(
        turn=request.turn,
        new_messages=request.conversation[request.new_messages_start :],
        flow=request.flow,
        architecture_commit=finalize_architecture_commit(decision.architecture_commit),
        planning_state_overlay=request.planning_state,
    )
    events: list[AIBuilderStreamEvent] = [build_status_event(status)]

    chained_turn = replace(
        request.turn,
        base_planning_state_version=new_version,
    )
    persisted_state = await request.repo.load_planning_state(
        session_id=chained_turn.session_id,
        tenant_id=chained_turn.tenant_id,
    )
    session_state = persisted_state or PlanningState.empty()
    turn_control = resolve_turn_control(
        session_state=session_state,
        selected_discovery_question_ids=(),
        requirements_confirmed=request.requirements_confirmed,
        ui_language=request.ui_language,
    )
    if isinstance(turn_control.decision, ConfirmRequirements):
        chained = await dispatch_server_decision(
            ServerDecisionDispatchRequest(
                repo=request.repo,
                turn=chained_turn,
                decision=turn_control.decision,
                conversation=request.conversation,
                new_messages_start=len(request.conversation),
                flow=request.flow,
                requirements_confirmed=request.requirements_confirmed,
                ui_language=request.ui_language,
                telemetry=request.telemetry,
                planning_state=session_state,
            )
        )
        events.extend(chained.events)
        new_version = chained.new_planning_state_version
    elif isinstance(turn_control.decision, GenerateProposal):
        return ServerDecisionDispatchResult(
            action_kind=action_kind,
            events=tuple(events),
            new_planning_state_version=new_version,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=session_state,
            ),
        )

    return ServerDecisionDispatchResult(
        action_kind=action_kind,
        events=tuple(events),
        new_planning_state_version=new_version,
    )


async def _dispatch_requirements_confirmation(
    request: ServerDecisionDispatchRequest,
    decision: ConfirmRequirements,
) -> ServerDecisionDispatchResult:
    requirements_payload = build_requirements_summary_payload(
        decision.payload,
        conversation=request.conversation,
        flow=request.flow,
        ui_language=request.ui_language,
    )
    request.conversation.append(
        ConversationMessage(
            role="assistant",
            content=decision.payload.summary,
            metadata=build_assistant_message_metadata(
                request.conversation,
                planner_telemetry=_server_turn_telemetry(
                    request,
                    action_kind="confirm_requirements",
                    architecture_commit_populated=False,
                    tool_call_count=0,
                ),
                base_metadata=requirements_summary_to_metadata(requirements_payload),
            ),
        )
    )
    new_version = await request.repo.commit_turn(
        turn=request.turn,
        new_messages=request.conversation[request.new_messages_start :],
        flow=request.flow,
        planning_state_overlay=request.planning_state,
    )
    return ServerDecisionDispatchResult(
        action_kind="confirm_requirements",
        events=(build_requirements_summary_event(requirements_payload),),
        new_planning_state_version=new_version,
    )


def build_requirements_summary_payload(
    payload: RequirementsSummaryPayload,
    *,
    conversation: list[ConversationMessage],
    flow: "Flow | None",
    ui_language: str | None,
) -> RequirementsSummaryPayload:
    normalized = normalize_requirements_summary_for_flow(
        payload.model_dump(),
        conversation=conversation,
        flow=flow,
        language=ui_language,
    )
    requirements_payload = RequirementsSummaryPayload.model_validate(normalized)
    return requirements_payload.model_copy(
        update={
            "requirements_version": build_requirements_version(requirements_payload)
        },
        deep=True,
    )


def _server_turn_telemetry(
    request: ServerDecisionDispatchRequest,
    *,
    action_kind: ServerDecisionKind,
    architecture_commit_populated: bool,
    tool_call_count: int,
) -> dict[str, object]:
    return build_planner_telemetry(
        request_id=request.telemetry.request_id,
        model=request.telemetry.litellm_model,
        finish_reason=None,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        tool_call_count=tool_call_count,
        used_auxiliary_llm=request.telemetry.used_auxiliary_llm,
        outcome_kind=f"server_{action_kind}",
        wall_clock_ms=0,
        llm_calls_made=0,
        repair_attempts=0,
        parse_repair_attempts=0,
        architecture_commit_populated=architecture_commit_populated,
    )


__all__ = [
    "ServerDecisionDispatchRequest",
    "ServerDecisionDispatchResult",
    "ServerDecisionProposalContinuation",
    "ServerDecisionTelemetry",
    "build_requirements_summary_payload",
    "dispatch_server_decision",
]
