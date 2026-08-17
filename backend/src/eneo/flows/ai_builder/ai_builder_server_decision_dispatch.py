from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, assert_never

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from eneo.flows.ai_builder.ai_builder_canonicalization import (
    SETTLED_SLOT_BY_NON_SLOT_QUESTION_ID,
    canonical_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_summary_to_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_requirements_summary_event,
    build_status_event,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_question_state import (
    question_ordinal_in_session,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
    resolve_locale,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
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
    RefuseArchitectureCommit,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    Locale,
    render_summary_label,
)
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
    "refuse_architecture_commit",
]


@dataclass(frozen=True, slots=True)
class ServerDecisionTelemetry:
    request_id: str
    litellm_model: str
    usage_tracker: ProposalTurnTelemetry


@dataclass(frozen=True, slots=True)
class ServerDecisionDispatchRequest:
    repo: "AIBuilderRepository"
    turn: SessionSendTurn
    decision: BuilderTurnDecision
    conversation: list[ConversationMessage]
    new_messages_start: int
    flow: "Flow | None"
    confirmed_requirements_version: str | None
    ui_language: str | None
    telemetry: ServerDecisionTelemetry
    planning_state: PlanningState
    discovery_assumptions: tuple[str, ...] = ()


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
                status=AIBuilderStatus.ARCHITECTURE_COMMITTED,
            )
        case ReviseArchitecture():
            return await _dispatch_architecture_commit(
                request,
                decision,
                action_kind="revise_architecture",
                status=AIBuilderStatus.ARCHITECTURE_REVISED,
            )
        case ConfirmRequirements():
            return await _dispatch_requirements_confirmation(request, decision)
        case RefuseArchitectureCommit():
            return ServerDecisionDispatchResult(
                action_kind="refuse_architecture_commit",
                events=(
                    build_ai_builder_error_event(
                        message=decision.message,
                        code=decision.code,
                        request_id=request.telemetry.request_id,
                    ),
                ),
                new_planning_state_version=request.turn.base_planning_state_version,
            )
        case GenerateProposal() as unhandled:
            raise ValueError(
                "GenerateProposal must be routed to the planner proposal path, "
                f"not dispatch_server_decision: {unhandled!r}"
            )
        case _ as unhandled:
            assert_never(unhandled)


async def _dispatch_question(
    request: ServerDecisionDispatchRequest,
    decision: AskCanonicalQuestion,
) -> ServerDecisionDispatchResult:
    question_id = decision.slot_name
    followup = decision.question or build_registry_question_followup(
        question_id,
        request.conversation,
        flow=request.flow,
        planning_state=request.planning_state,
    )
    if followup is not None:
        followup = replace(
            followup,
            question_data=_situate_question(
                followup.question_data,
                conversation=request.conversation,
                flow=request.flow,
                planned_remaining=decision.planned_remaining,
                locale=resolve_locale(request.ui_language),
            ),
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
            planning_state=request.planning_state,
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


def _situate_question(
    payload: StructuredQuestionPayload,
    *,
    conversation: list[ConversationMessage],
    flow: Flow | None,
    planned_remaining: int | None,
    locale: Locale,
) -> StructuredQuestionPayload:
    """Place this question in the interview, and in the flow it is asked about.

    Dispatch is where every question kind meets, whichever owner wrote it, and
    the only place that both holds the flow and emits the payload, so the two
    are stamped once here rather than in each question owner.

    The payload's own id is what counts for the number, because it is the id
    persistence stamps on the assistant message, and therefore the id the next
    turn counts. The question is not persisted yet, so the conversation holds
    exactly the ones already asked.

    What is still ahead cannot be counted here, because dispatch sees one
    question and not the queue it came from. It travels on the decision, from
    the turn control that ranked the queue, and stays null for the questions
    that turn control decides ahead of that queue.

    While editing, the only recommendation Eneo makes is to keep what the flow
    already does. Anything else is a proposal to change something that is
    already running, and a badge is not how a change like that should be put to
    a user. So the recommendation survives only where it can be shown to match
    the current value, and is dropped wherever that cannot be shown — including
    a flow whose answer none of the offered options carries, where every option
    on screen would change the flow.

    The topic is the catalog's own summary label for the slot this question
    settles, taken from the owner the requirements summary reads, so a question
    and the summary row the user later confirms cannot name one topic two ways.

    The result is revalidated rather than copied into place, because a copy
    skips the model's own rules and this is where the payload's last facts are
    decided.
    """

    current_option_id = _current_option_id(payload, flow=flow)
    keeps_recommendation = (
        payload.recommended_option_id == current_option_id if flow is not None else True
    )
    return StructuredQuestionPayload.model_validate(
        payload.model_dump()
        | {
            "question_index": question_ordinal_in_session(
                conversation, question_id=payload.question_id
            ),
            "questions_planned_remaining": planned_remaining,
            "topic": _question_topic(payload, locale=locale),
            "current_option_id": current_option_id,
            "recommended_option_id": (
                payload.recommended_option_id if keeps_recommendation else None
            ),
            "recommended_option_evidence": (
                payload.recommended_option_evidence if keeps_recommendation else None
            ),
        }
    )


def _question_topic(
    payload: StructuredQuestionPayload,
    *,
    locale: Locale,
) -> str | None:
    """What this question is about, named the way the summary names it.

    Only a catalog slot has a name to give. A question that settles none of
    them — schema direction — is left unnamed rather than described from its
    own wording, which would be a second name for the same topic with nothing
    keeping the two in step. A non-slot question that settles exactly one slot
    (runtime field details settle the runtime-metadata slot) is named after it.
    """

    question_id = canonical_question_id(payload.question_id)
    slot_name = SETTLED_SLOT_BY_NON_SLOT_QUESTION_ID.get(question_id, question_id)
    if slot_name not in QUESTION_CATALOG:
        return None
    return render_summary_label(slot_name, locale)


def _current_option_id(
    payload: StructuredQuestionPayload,
    *,
    flow: Flow | None,
) -> str | None:
    """The offered option the flow being edited uses for this slot today.

    Read off the flow through the same capability profile the rest of the
    Builder reads it through, so there is one derivation of what a flow does and
    no second reading of its steps. That profile reports a slot only when the
    flow answers it with a value the catalog can offer: a run that takes both a
    recording and uploaded documents is not one of the materials the question
    lists, and no current option is named rather than a wrong one.
    """

    if flow is None:
        return None
    values = build_flow_discovery_defaults(flow).get(
        canonical_question_id(payload.question_id)
    )
    if values is None or len(values) != 1:
        return None
    current_value = next(iter(values))
    named = [
        option.id
        for option in payload.options
        if option.id is not None and option.value == current_value
    ]
    return named[0] if len(named) == 1 else None


async def _dispatch_architecture_commit(
    request: ServerDecisionDispatchRequest,
    decision: CommitArchitecture | ReviseArchitecture,
    *,
    action_kind: ServerDecisionKind,
    status: AIBuilderStatus,
) -> ServerDecisionDispatchResult:
    new_version = await request.repo.commit_turn(
        turn=request.turn,
        new_messages=request.conversation[request.new_messages_start :],
        flow=request.flow,
        architecture_commit=finalize_architecture_commit(decision.architecture_commit),
        planning_state=request.planning_state,
        complete_turn=False,
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
    # The chained confirmation reads the same disclosure the direct path would
    # have produced from this exact persisted state.
    turn_control = resolve_turn_control(
        session_state=session_state,
        selected_discovery_question_ids=(),
        requirements_disclosure=build_requirements_disclosure(
            session_state,
            ui_language=request.ui_language,
            discovery_assumptions=request.discovery_assumptions,
            is_edit_mode=request.flow is not None,
        ),
        confirmed_requirements_version=request.confirmed_requirements_version,
        ui_language=request.ui_language,
        is_edit_mode=request.flow is not None,
    )
    if isinstance(turn_control.decision, ConfirmRequirements) or (
        isinstance(turn_control.decision, AskCanonicalQuestion)
        and turn_control.decision.slot_name == "runtime_metadata_field_details"
    ):
        chained = await dispatch_server_decision(
            ServerDecisionDispatchRequest(
                repo=request.repo,
                turn=chained_turn,
                decision=turn_control.decision,
                conversation=request.conversation,
                new_messages_start=len(request.conversation),
                flow=request.flow,
                confirmed_requirements_version=request.confirmed_requirements_version,
                ui_language=request.ui_language,
                telemetry=request.telemetry,
                planning_state=session_state,
                discovery_assumptions=request.discovery_assumptions,
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
    # The decision already carries the complete, versioned disclosure. Nothing
    # here may rewrite it: persisting or emitting a different object than the
    # one that was hashed is how confirmation grew a second truth.
    requirements_payload = decision.payload
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
        planning_state=request.planning_state,
    )
    return ServerDecisionDispatchResult(
        action_kind="confirm_requirements",
        events=(build_requirements_summary_event(requirements_payload),),
        new_planning_state_version=new_version,
    )


def _server_turn_telemetry(
    request: ServerDecisionDispatchRequest,
    *,
    action_kind: ServerDecisionKind,
    architecture_commit_populated: bool,
    tool_call_count: int,
) -> dict[str, object]:
    telemetry = request.telemetry.usage_tracker.build_planner_telemetry(
        tool_call_count=tool_call_count
    )
    telemetry.update(
        outcome_kind=f"server_{action_kind}",
        architecture_commit_populated=architecture_commit_populated,
    )
    return telemetry


__all__ = [
    "ServerDecisionDispatchRequest",
    "ServerDecisionDispatchResult",
    "ServerDecisionProposalContinuation",
    "ServerDecisionTelemetry",
    "dispatch_server_decision",
]
