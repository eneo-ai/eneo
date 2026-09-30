"""The requirements card's own prose is display copy, never the user's words.

Every Builder turn rebuilds the planning state from the conversation. The card
the server rendered earlier sits in that conversation as an assistant message;
reading its sentences back as if the user had typed them made a slot the
server had picked come back as evidence for itself. Accepted facts travel
through the typed attestation channel, and nothing else of the card is read.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_unprompted_user_text,
)
from eneo.flows.ai_builder.ai_builder_slot_interaction_policy import (
    SLOT_INTERACTION_POLICIES,
    evaluate_slot_interaction,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.ai_builder.question_catalog import legal_slot_values
from eneo.flows.domain.flow import Flow, FlowStep
from tests.unittests.flows.ai_builder.requirements_card_test_support import (
    pending_card_message,
)

# Says nothing about what the flow takes in or delivers.
_UNRELATED_USER_TEXT = "Jag vill ha hjälp med mina ärenden."


def _user(content: str = _UNRELATED_USER_TEXT) -> ConversationMessage:
    return ConversationMessage(role="user", content=content)


def _saved_flow() -> Flow:
    """An existing flow, as an edit session observes it."""

    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Strukturerad samtalsrapport",
        description="Befintligt dokumentflöde",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Läs underlaget",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="text",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skapa DOCX",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="docx",
            ),
        ],
    )


def _slots(
    conversation: list[ConversationMessage], flow: Flow | None = None
) -> dict[str, dict[str, object]]:
    return {
        name: slot.model_dump()
        for name, slot in build_planning_state_from_conversation(
            conversation, flow=flow
        ).resolved_slots.items()
    }


def test_pending_card_prose_adds_no_slot_to_the_users_words() -> None:
    conversation = [_user()]
    card = pending_card_message(
        runtime_input="documents",
        terminal_output="docx_document",
        ui_language="sv",
    )

    assert _slots([*conversation, card]) == _slots(conversation) == {}


@pytest.mark.parametrize("observes_saved_flow", [False, True])
@pytest.mark.parametrize("ui_language", ["sv", "en"])
@pytest.mark.parametrize(
    "terminal_output", sorted(legal_slot_values("terminal_output"))
)
@pytest.mark.parametrize(
    "runtime_input", sorted(legal_slot_values("primary_runtime_input"))
)
def test_no_card_rendering_changes_what_the_users_words_resolve(
    runtime_input: str,
    terminal_output: str,
    ui_language: str,
    observes_saved_flow: bool,
) -> None:
    flow = _saved_flow() if observes_saved_flow else None
    conversation = [_user()]
    card = pending_card_message(
        runtime_input=runtime_input,
        terminal_output=terminal_output,
        ui_language=ui_language,
    )

    assert _slots([*conversation, card], flow) == _slots(conversation, flow)


def test_accepting_the_card_resolves_its_values_and_a_later_card_does_not_unpin_them() -> (
    None
):
    first = pending_card_message(
        runtime_input="documents",
        terminal_output="docx_document",
        ui_language="sv",
    )
    version = first.metadata["requirements_version"]  # type: ignore[index]
    confirmation = ConversationMessage(
        role="user",
        content="",
        metadata={"requirements_confirmed": True, "requirements_version": version},
    )
    later = pending_card_message(
        runtime_input="text",
        terminal_output="pdf_document",
        ui_language="sv",
    )

    accepted = _slots([_user(), first, confirmation])
    assert {
        name: (accepted[name]["value"], accepted[name]["source"])
        for name in ("primary_runtime_input", "terminal_output")
    } == {
        "primary_runtime_input": ("documents", "requirements_summary"),
        "terminal_output": ("docx_document", "requirements_summary"),
    }
    assert accepted["terminal_output"]["confidence"] == "high"
    assert _slots([_user(), first, confirmation, later]) == accepted


def test_a_user_who_names_the_output_still_resolves_it_with_a_card_on_screen() -> None:
    conversation = [_user("Flödet ska producera ett PDF-dokument.")]
    card = pending_card_message(
        runtime_input="text",
        terminal_output="docx_document",
        ui_language="sv",
    )

    without_card = _slots(conversation)
    assert without_card["terminal_output"]["value"] == "pdf_document"
    assert _slots([*conversation, card]) == without_card


def test_card_prose_is_not_part_of_the_users_text() -> None:
    card = pending_card_message(
        runtime_input="documents",
        terminal_output="docx_document",
        ui_language="en",
    )

    assert (
        aggregate_unprompted_user_text([_user(), card])
        == _UNRELATED_USER_TEXT.casefold()
    )


def test_card_prose_changes_no_interaction_decision() -> None:
    conversation = [_user()]
    card = pending_card_message(
        runtime_input="documents",
        terminal_output="docx_document",
        ui_language="sv",
    )

    def decisions(messages: list[ConversationMessage]) -> dict[str, object]:
        state = build_planning_state_from_conversation(messages)
        return {
            name: evaluate_slot_interaction(
                policy, state, freeform_text=_UNRELATED_USER_TEXT
            )
            for name, policy in SLOT_INTERACTION_POLICIES.items()
        }

    assert decisions([*conversation, card]) == decisions(conversation)
