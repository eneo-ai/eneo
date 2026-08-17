"""Turns that answer the user without proposing a plan.

Two of them exist. The model can decline a change the edit contract cannot
carry — a step's model lives in the step editor and nowhere else — and the
server can refuse a scoped revision it knows the model cannot satisfy. Both
own their user-visible sentence here, and both are stored like an accepted
proposal, so the conversation records what was asked and what was answered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import build_text_event
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_tool_names import DECLINE_FLOW_CHANGE_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import ProposalToolSchema
from eneo.flows.ai_builder.planning_state import PlanningState

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

DeclineReason = Literal["model_choice_belongs_to_step_editor"]

DECLINE_REASONS: Final[tuple[DeclineReason, ...]] = get_args(DeclineReason)

_DECLINE_MESSAGES: Final[dict[DeclineReason, dict[str, str]]] = {
    "model_choice_belongs_to_step_editor": {
        "sv": "Jag kan inte byta modell åt dig — det gör du i stegredigeraren.",
        "en": "I can't change the model for you — you pick it in the step editor.",
    },
}


def build_decline_flow_change_tool_schema() -> ProposalToolSchema:
    return cast(
        ProposalToolSchema,
        {
            "type": "function",
            "function": {
                "name": DECLINE_FLOW_CHANGE_TOOL_NAME,
                "description": (
                    "Decline a request this flow edit cannot carry out, instead of "
                    "changing something the user did not ask about. Use it only for "
                    "a listed reason; edit the flow with propose_flow otherwise."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["reason"],
                    "additionalProperties": False,
                    "properties": {
                        "reason": {
                            "type": "string",
                            "enum": list(DECLINE_REASONS),
                            "description": (
                                "model_choice_belongs_to_step_editor: the user asked "
                                "to change which AI model a step runs on. The flow "
                                "edit contract has no model field; the user changes "
                                "it in the step editor."
                            ),
                        }
                    },
                },
            },
        },
    )


def decline_reason_from_arguments(arguments: dict[str, Any]) -> DeclineReason | None:
    """Read the one closed argument, or nothing.

    The schema is a closed object with a single enum member, so anything the
    provider adds beside it is outside the contract and the turn falls back to
    ordinary proposal handling rather than guessing an intent.
    """

    if set(arguments) != {"reason"}:
        return None
    reason = arguments["reason"]
    if isinstance(reason, str) and reason in DECLINE_REASONS:
        return reason
    return None


def decline_message(reason: DeclineReason, *, ui_language: str | None) -> str:
    messages = _DECLINE_MESSAGES[reason]
    return messages["en" if _uses_english(ui_language) else "sv"]


def _uses_english(ui_language: str | None) -> bool:
    return ui_language is not None and ui_language.casefold().startswith("en")


SCOPED_REVISION_OUT_OF_REACH_MESSAGES: Final[dict[str, str]] = {
    "sv": (
        "Jag kunde inte göra den ändringen på bara det markerade steget. "
        "Redigera hela planen så kan jag göra den där."
    ),
    "en": (
        "I couldn't make that change to the selected step alone. Edit the "
        "whole plan and I can make it there."
    ),
}


def scoped_revision_out_of_reach_message(*, ui_language: str | None) -> str:
    """What the user is told when only a whole-plan edit can carry the change."""

    return SCOPED_REVISION_OUT_OF_REACH_MESSAGES[
        "en" if _uses_english(ui_language) else "sv"
    ]


async def persist_non_plan_turn(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    tool_name: str,
    arguments: dict[str, Any],
    tool_content: str,
    message: str,
    tool_call_id: str,
    base_assistant_metadata: dict[str, Any] | None,
    usage_tracker: ProposalTurnTelemetry | None,
    planning_state: PlanningState,
    flow: "Flow | None",
) -> tuple[AIBuilderStreamEvent, ...]:
    """Store an answered turn the same way an accepted proposal is stored.

    The answer the user reads is part of the conversation, so the next turn
    sees that the Builder already explained itself. No plan is created and the
    plan the session already has stays current.
    """

    tool_call = make_persisted_assistant_tool_call(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
    )
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=message,
            # The turn reports the call it actually made, whether the answer was
            # decided on the first attempt or after a repair.
            metadata=assistant_metadata_with_usage(
                conversation=conversation,
                base_metadata=base_assistant_metadata,
                usage_tracker=usage_tracker,
                tool_calls=[tool_call],
            ),
            tool_calls=[tool_call.model_dump(mode="json")],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=tool_content,
            tool_call_id=tool_call_id,
        )
    )
    # Before the turn is closed, while this send still holds the lease: the
    # plan this turn did not replace goes back to being approvable.
    await repo.restore_awaiting_approval_after_answered_turn(turn=turn)
    await repo.commit_turn(
        turn=turn,
        new_messages=conversation[new_messages_start:],
        flow=flow,
        planning_state=planning_state,
    )
    return (build_text_event(message),)
