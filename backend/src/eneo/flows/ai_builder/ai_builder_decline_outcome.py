"""The non-mutating outcome a revision turn can return instead of a plan.

A revision turn otherwise offers exactly one forced tool, so a request the
Builder must not carry out — changing a step's model, which lives in the step
editor and nowhere else — leaves the model with nothing legal to answer except
a change the user never asked for. This contract gives it a typed way to
decline, and keeps the sentence the user reads on the server: the model
chooses the reason, never the wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import build_text_event
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
    reason = arguments.get("reason")
    if isinstance(reason, str) and reason in DECLINE_REASONS:
        return reason
    return None


def decline_message(reason: DeclineReason, *, ui_language: str | None) -> str:
    messages = _DECLINE_MESSAGES[reason]
    return messages["en" if _uses_english(ui_language) else "sv"]


def _uses_english(ui_language: str | None) -> bool:
    return ui_language is not None and ui_language.casefold().startswith("en")


@dataclass(frozen=True, slots=True)
class DeclinedFlowChangeResult:
    events: tuple[AIBuilderStreamEvent, ...]
    new_planning_state_version: int


async def persist_declined_flow_change(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    reason: DeclineReason,
    message: str,
    tool_call_id: str,
    assistant_metadata: dict[str, Any] | None,
    planning_state: PlanningState,
    flow: "Flow | None",
) -> DeclinedFlowChangeResult:
    """Store the declined turn the same way an accepted proposal is stored.

    The answer the user reads is part of the conversation, so the next turn
    sees that the Builder already explained itself. No plan is created and the
    plan the session already has stays current.
    """

    tool_call = make_persisted_assistant_tool_call(
        tool_call_id=tool_call_id,
        tool_name=DECLINE_FLOW_CHANGE_TOOL_NAME,
        arguments={"reason": reason},
    )
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=message,
            metadata=assistant_metadata,
            tool_calls=[tool_call.model_dump(mode="json")],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content="Flow change declined; no plan was proposed.",
            tool_call_id=tool_call_id,
        )
    )
    new_version = await repo.commit_turn(
        turn=turn,
        new_messages=conversation[new_messages_start:],
        flow=flow,
        planning_state=planning_state,
    )
    return DeclinedFlowChangeResult(
        events=(build_text_event(message),),
        new_planning_state_version=new_version,
    )
