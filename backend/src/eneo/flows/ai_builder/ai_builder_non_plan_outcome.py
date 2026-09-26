"""Turns that answer the user without proposing a plan.

The model can decline a change the edit contract cannot carry — a step's
model lives in the step editor and nowhere else. The server answers instead
of planning when it knows no plan can be made this turn: a scoped revision
the model cannot satisfy, a selected step that changed under the proposal,
an edit only the user can fix, or text the user wrote that could not be
read. Each owns its user-visible sentence here, and each is stored like an
accepted proposal, so the conversation records what was asked and what was
answered.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PersistedAssistantToolCall,
    UnsettledUserText,
    make_persisted_assistant_tool_call,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import build_text_event
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    primary_input_reserved_names,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_NAME_LENGTH,
    MAX_DIAGNOSTIC_NAMES,
    NonPlanKind,
    NonPlanOutcome,
    ProposalAnswer,
    RequiredAction,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_tool_names import DECLINE_FLOW_CHANGE_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import ProposalToolSchema
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.flow_authoring_spec import InputType

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
# The same declines in a selected-step edit, naming the step as it is shown.
_SELECTED_STEP_DECLINE_MESSAGES: Final[dict[DeclineReason, dict[str, str]]] = {
    "model_choice_belongs_to_step_editor": {
        "sv": (
            "Jag kan inte byta modell åt dig. Öppna steget {step} i "
            "stegredigeraren och välj modellen där."
        ),
        "en": (
            "I can't change the model for you. Open the step {step} in the step "
            "editor and pick the model there."
        ),
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


def decline_message(
    reason: DeclineReason, *, ui_language: str | None, step_name: str | None = None
) -> str:
    language = "en" if _uses_english(ui_language) else "sv"
    if step_name:
        return _SELECTED_STEP_DECLINE_MESSAGES[reason][language].format(
            step=_code_span(_shortened(step_name))
        )
    return _DECLINE_MESSAGES[reason][language]


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


def scoped_revision_out_of_reach_answer(
    *, target_step_ref: str | None, ui_language: str | None
) -> ProposalAnswer:
    return ProposalAnswer(
        answer=scoped_revision_out_of_reach_message(ui_language=ui_language),
        outcome=non_plan_outcome(
            "scoped_revision_out_of_reach",
            "edit_whole_plan",
            affected=(target_step_ref,) if target_step_ref else (),
        ),
    )


def non_plan_outcome(
    kind: NonPlanKind,
    required_action: RequiredAction,
    *,
    affected: Sequence[str] = (),
) -> NonPlanOutcome:
    return NonPlanOutcome(
        kind=kind,
        required_action=required_action,
        affected=tuple(_shortened(name) for name in affected[:MAX_DIAGNOSTIC_NAMES]),
        affected_remaining=max(0, len(affected) - MAX_DIAGNOSTIC_NAMES),
    )


# A mark or joiner belongs to the character before it.
_ATTACHED_CATEGORIES: Final = frozenset({"Mn", "Mc", "Me", "Cf"})


def _shortened(name: str) -> str:
    """``name`` within the bound, cut with an ellipsis between whole characters."""

    if len(name) <= MAX_DIAGNOSTIC_NAME_LENGTH:
        return name
    cut = MAX_DIAGNOSTIC_NAME_LENGTH - 1
    while cut and (
        unicodedata.category(name[cut]) in _ATTACHED_CATEGORIES
        or unicodedata.category(name[cut - 1]) == "Cf"
    ):
        cut -= 1
    return name[:cut] + "…"


# The failures only the user can fix that end an edit with an answer, keyed by
# the failure code their raise site declares. Template selection, unreadable
# templates and unresolved or invalid placeholders keep their typed error: the
# chat shows those with their own card and action.
_USER_ACTION_OUTCOMES: Final[dict[str, tuple[NonPlanKind, RequiredAction]]] = {
    "template_placeholder_depth_exceeded": (
        "template_placeholder_too_deep",
        "edit_template_placeholders",
    ),
    "template_placeholder_path_too_long": (
        "template_placeholder_too_long",
        "edit_template_placeholders",
    ),
    "template_placeholder_count_exceeded": (
        "template_has_too_many_placeholders",
        "simplify_template",
    ),
    "confirmed_form_field_incompatible": (
        "form_field_conflicts_with_run_input",
        "rename_form_field",
    ),
}

_USER_ACTION_MESSAGES: Final[dict[NonPlanKind, dict[str, str]]] = {
    "template_placeholder_too_deep": {
        "sv": (
            "Fältet {names} i mallen har för många nivåer. Förenkla fältnamnet i "
            "mallen och försök igen."
        ),
        "en": (
            "The field {names} in the template has too many levels. Simplify the "
            "field name in the template and try again."
        ),
    },
    "template_placeholder_too_long": {
        "sv": "Fältnamnet {names} i mallen är för långt. Korta det i mallen och försök igen.",
        "en": (
            "The field name {names} in the template is too long. Shorten it in the "
            "template and try again."
        ),
    },
    "template_has_too_many_placeholders": {
        "sv": (
            "Mallen har fler fält med punkt i namnet (som kund.namn) än som kan "
            "läggas till automatiskt i ett förberedande steg (högst {max_paths}). "
            "Fält som ett tidigare steg redan tar fram räknas inte. Minska antalet "
            "sådana fält i mallen, eller låt ett tidigare steg ta fram några av "
            "dem, och försök igen."
        ),
        "en": (
            "The template has more fields with a dot in their name (like "
            "customer.name) than can be added automatically to one preparation "
            "step (at most {max_paths}). Fields an earlier step already produces "
            "don't count. Reduce the number of those fields in the template, or "
            "have an earlier step produce some of them, and try again."
        ),
    },
    "form_field_conflicts_with_run_input": {
        "sv": (
            "Formulärfältet {names} har samma namn som det flödet tar emot när det "
            "körs. Byt namn på fältet eller ta bort det och försök igen. "
            "Reserverade namn: {reserved}."
        ),
        "en": (
            "The form field {names} has the same name as what the flow receives "
            "when it runs. Rename the field or remove it and try again. Reserved "
            "names: {reserved}."
        ),
    },
}
# The same answers when they name more than one thing.
_SEVERAL_NAMES_MESSAGES: Final[dict[NonPlanKind, dict[str, str]]] = {
    "form_field_conflicts_with_run_input": {
        "sv": (
            "Formulärfälten {names} har samma namn som det flödet tar emot när det "
            "körs. Byt namn på fälten eller ta bort dem och försök igen. "
            "Reserverade namn: {reserved}."
        ),
        "en": (
            "The form fields {names} have the same names as what the flow receives "
            "when it runs. Rename the fields or remove them and try again. "
            "Reserved names: {reserved}."
        ),
    },
}


def user_action_answer(
    error: AIBuilderArchitectureError, *, ui_language: str | None
) -> ProposalAnswer | None:
    """The answer for a failure only the user can fix, or None to keep the error."""

    failure_code = error.failure_code or ""
    mapped = _USER_ACTION_OUTCOMES.get(failure_code)
    if error.repair_disposition != "user_action" or mapped is None:
        return None
    outcome = non_plan_outcome(*mapped, affected=error.affected)
    language = "en" if _uses_english(ui_language) else "sv"
    messages = (
        _SEVERAL_NAMES_MESSAGES.get(outcome.kind) if len(error.affected) > 1 else None
    ) or _USER_ACTION_MESSAGES[outcome.kind]
    runtime_input_type = error.log_context.get("runtime_input_type")
    reserved = (
        primary_input_reserved_names(InputType(runtime_input_type))
        if isinstance(runtime_input_type, str)
        else ()
    )
    return ProposalAnswer(
        answer=messages[language].format(
            names=_name_list(outcome.affected, outcome.affected_remaining, language),
            max_paths=error.log_context.get("max_paths"),
            reserved=_name_list(reserved, 0, language),
        ),
        outcome=outcome,
        codes=frozenset({failure_code}),
    )


def _name_list(names: Sequence[str], remaining: int, language: str) -> str:
    more, conjunction = ("{} more", "and") if language == "en" else ("{} till", "och")
    items = [_code_span(name) for name in names]
    if remaining:
        items.append(more.format(remaining))
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"


def _code_span(name: str) -> str:
    """``name`` as a Markdown code span, which the chat shows exactly as written."""

    fence = "`"
    while fence in name:
        fence += "`"
    padding = " " if name[:1] in ("`", " ") or name[-1:] in ("`", " ") else ""
    return f"{fence}{padding}{name}{padding}{fence}"


_STALE_SAVED_STEP_REVISION_MESSAGES: Final[dict[str, str]] = {
    "sv": (
        "Flödet har ändrats sedan det här förslaget skapades. "
        "Välj steget igen i det aktuella flödet för att fortsätta."
    ),
    "en": (
        "The flow has changed since this proposal was created. "
        "Select the step again in the current flow to continue."
    ),
}


def stale_saved_step_revision_message(*, ui_language: str | None) -> str:
    return _STALE_SAVED_STEP_REVISION_MESSAGES[
        "en" if _uses_english(ui_language) else "sv"
    ]


# The unread answer holds on the turn that could not read the text and on any
# later turn (a click included) that waits for it to be sent again.
_UNSETTLED_TEXT_ANSWERS: Final[dict[UnsettledUserText, dict[str, str]]] = {
    "unread": {
        "sv": "Jag kunde inte läsa det du skrev. Skicka det igen, så fortsätter vi.",
        "en": (
            "I couldn't read what you wrote. Please send it again, and we'll continue."
        ),
    },
    "speaker_naming_without_edit": {
        "sv": (
            "Jag är osäker på hur transkriptet ska granskas: ska den som granskar "
            "kunna ändra talarnas namn, eller bara läsa transkriptet? Skriv vilket "
            "du menar, så fortsätter vi."
        ),
        "en": (
            "I'm not sure how the transcript should be reviewed: should the "
            "reviewer be able to change the speakers' names, or only read the "
            "transcript? Tell me which, and we'll continue."
        ),
    },
}


def unsettled_text_answer(
    unsettled: UnsettledUserText, *, ui_language: str | None
) -> str:
    """What the user is told while text they wrote cannot be built on yet."""

    return _UNSETTLED_TEXT_ANSWERS[unsettled][
        "en" if _uses_english(ui_language) else "sv"
    ]


async def persist_non_plan_turn(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    tool_content: str | None = None,
    message: str,
    tool_call_id: str | None = None,
    base_assistant_metadata: dict[str, Any] | None,
    usage_tracker: ProposalTurnTelemetry | None,
    planning_state: PlanningState,
    flow: "Flow | None",
    outcome: NonPlanOutcome | None = None,
) -> tuple[AIBuilderStreamEvent, ...]:
    """Store an answered turn the same way an accepted proposal is stored.

    The answer the user reads is part of the conversation, so the next turn
    sees that the Builder already explained itself. No plan is created and the
    plan the session already has stays current.
    """

    tool_calls: list[PersistedAssistantToolCall] = []
    if tool_name is not None:
        assert tool_call_id is not None and arguments is not None
        assert tool_content is not None
        tool_calls.append(
            make_persisted_assistant_tool_call(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
            )
        )
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=message,
            metadata=assistant_metadata_with_usage(
                conversation=conversation,
                base_metadata=(
                    base_assistant_metadata
                    if outcome is None
                    else {
                        **(base_assistant_metadata or {}),
                        "non_plan_outcome": {
                            "kind": outcome.kind,
                            "required_action": outcome.required_action,
                            "affected": list(outcome.affected),
                            "affected_remaining": outcome.affected_remaining,
                        },
                    }
                ),
                usage_tracker=usage_tracker,
                tool_calls=tool_calls or None,
            ),
            tool_calls=[call.model_dump(mode="json") for call in tool_calls] or None,
        )
    )
    if tool_calls:
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
