from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_accepted_action_rendering import (
    RequirementsSummaryRenderContext,
    build_accepted_action_events,
    build_accepted_action_messages,
)
from intric.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
    compute_unresolved_core_slots,
)
from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_discovery_followup,
    build_registry_question_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_events import build_text_event
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    ConfirmRequirementsAction,
    OrchestrationContext,
    PlannerOutput,
)
from intric.flows.ai_builder.ai_builder_planner_turn import (
    PlannerTurnResult,
    build_planner_litellm_kwargs,
    run_planner_turn,
)
from intric.flows.ai_builder.ai_builder_question_state import (
    derive_asked_question_state,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_response_format import (
    PlannerResponseFormatSelection,
)
from intric.flows.ai_builder.ai_builder_server_actions import (
    build_server_planner_output,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)

_SERVER_SLOT_TO_DISCOVERY_QUESTION_ID: dict[str, str] = {
    "primary_runtime_input": "input_material_mode",
    "terminal_output": "final_output_mode",
}


@dataclass(frozen=True, slots=True)
class BackendSelectedQuestionDispatchRequest:
    repo: AIBuilderRepository
    turn: SessionSendTurn
    server_output: PlannerOutput | None
    conversation: list[ConversationMessage]
    new_messages_start: int
    flow: "Flow | None"
    discovery_analysis: DiscoveryAnalysis | None = None


@dataclass(frozen=True, slots=True)
class DispatchedActionEventRequest:
    repo: AIBuilderRepository
    litellm_client: Any
    turn: SessionSendTurn
    turn_result: PlannerTurnResult
    conversation: list[ConversationMessage]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    response_format_selection: PlannerResponseFormatSelection
    flow: "Flow | None"
    requirements_confirmed: bool
    ui_language: str | None
    planner_temperature: float


async def dispatch_backend_selected_question_if_any(
    request: BackendSelectedQuestionDispatchRequest,
) -> list[dict[str, str]] | None:
    if request.server_output is None:
        return None
    action = request.server_output.planner_action
    if not isinstance(action, AskQuestionAction):
        return None

    question_id = _discovery_question_id_for_server_slot(action.payload.slot_name)
    followup = build_registry_question_followup(
        question_id,
        request.conversation,
        flow=request.flow,
    )
    if followup is None:
        discovery_followup = build_discovery_followup(
            request.conversation,
            flow=request.flow,
            analysis=request.discovery_analysis,
        )
        if discovery_followup is not None:
            if discovery_followup.question_data.get("question_id") == question_id:
                followup = discovery_followup
            else:
                logger.warning(
                    "AI Builder server question fallback selected a different "
                    "discovery question.",
                    extra={
                        "requested_question_id": question_id,
                        "fallback_question_id": (
                            discovery_followup.question_data.get("question_id")
                        ),
                    },
                )

    if followup is None:
        return [build_text_event(action.payload.prompt)]

    persisted = await persist_backend_question(
        repo=request.repo,
        turn=request.turn,
        conversation=request.conversation,
        new_messages_start=request.new_messages_start,
        question=followup,
        flow=request.flow,
        assistant_metadata=build_assistant_message_metadata(
            request.conversation,
            tool_calls=[{"name": "ask_structured_question"}],
        ),
    )
    return persisted.events


async def build_dispatched_action_events(
    request: DispatchedActionEventRequest,
) -> list[dict[str, str]]:
    accepted_output = request.turn_result.accepted_output
    if accepted_output is None:
        return []

    render_context = RequirementsSummaryRenderContext(
        conversation=request.conversation,
        flow=request.flow,
        ui_language=request.ui_language,
    )
    events = build_accepted_action_events(accepted_output, context=render_context)

    chained_result = await _dispatch_chained_confirm_after_commit_if_needed(request)
    if (
        chained_result is not None
        and chained_result.kind == "dispatched"
        and chained_result.accepted_output is not None
        and isinstance(
            chained_result.accepted_output.planner_action, ConfirmRequirementsAction
        )
    ):
        events.extend(
            build_accepted_action_events(
                chained_result.accepted_output,
                context=render_context,
            )
        )

    return events


async def _dispatch_chained_confirm_after_commit_if_needed(
    request: DispatchedActionEventRequest,
) -> PlannerTurnResult | None:
    accepted_output = request.turn_result.accepted_output
    dispatch_result = request.turn_result.dispatch_result
    if (
        accepted_output is None
        or dispatch_result is None
        or not isinstance(accepted_output.planner_action, CommitArchitectureAction)
    ):
        return None

    chained_turn = replace(
        request.turn,
        base_planning_state_version=dispatch_result.new_planning_state_version,
    )
    persisted_state = await request.repo.load_planning_state(
        session_id=chained_turn.session_id,
        tenant_id=chained_turn.tenant_id,
    )
    session_state = persisted_state or PlanningState.empty()
    unresolved_core_slots = compute_unresolved_core_slots(session_state)
    action_policy = build_planner_action_policy(
        session_state=session_state,
        unresolved_architectural_choices=unresolved_core_slots,
        selected_discovery_question_ids=frozenset(),
        requirements_confirmed=request.requirements_confirmed,
    )
    server_output = build_server_planner_output(
        action_policy=action_policy,
        session_state=session_state,
        base_planning_state_version=chained_turn.base_planning_state_version,
        ui_language=request.ui_language,
    )
    if server_output is None or not isinstance(
        server_output.planner_action, ConfirmRequirementsAction
    ):
        return None

    asked_question_state = derive_asked_question_state(request.conversation)
    orchestration_context = OrchestrationContext.for_turn(
        current_version=chained_turn.base_planning_state_version,
        session_state=session_state,
        asked_question_state=asked_question_state,
        unresolved_architectural_choices=unresolved_core_slots,
        action_policy=action_policy,
    )
    render_context = RequirementsSummaryRenderContext(
        conversation=request.conversation,
        flow=request.flow,
        ui_language=request.ui_language,
    )

    return await run_planner_turn(
        repo=request.repo,
        litellm_client=request.litellm_client,
        litellm_model=request.litellm_model,
        litellm_kwargs=build_planner_litellm_kwargs(
            litellm_kwargs=request.litellm_kwargs,
            max_tokens=1,
            temperature=request.planner_temperature,
            response_format_selection=request.response_format_selection,
        ),
        turn=chained_turn,
        flow=request.flow,
        base_messages=[],
        orchestration_context=orchestration_context,
        build_new_messages=partial(
            build_accepted_action_messages,
            context=render_context,
            new_messages_start=len(request.conversation),
            used_auxiliary_llm=False,
        ),
        precomputed_output=server_output,
    )


def _discovery_question_id_for_server_slot(slot_name: str) -> str:
    return _SERVER_SLOT_TO_DISCOVERY_QUESTION_ID.get(slot_name, slot_name)


__all__ = [
    "BackendSelectedQuestionDispatchRequest",
    "DispatchedActionEventRequest",
    "build_dispatched_action_events",
    "dispatch_backend_selected_question_if_any",
]
