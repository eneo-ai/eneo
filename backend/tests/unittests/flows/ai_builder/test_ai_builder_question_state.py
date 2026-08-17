from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_question_state import (
    last_answered_question,
    question_ordinal_in_session,
)


def test_last_answered_question_returns_latest_asked_with_text_reply() -> None:
    result = last_answered_question(
        [
            ConversationMessage(role="user", content="Build a flow."),
            ConversationMessage(
                role="assistant",
                content="Which output?",
                metadata={"question_id": "terminal_output"},
            ),
            ConversationMessage(role="user", content="en fil jag kan ladda ner"),
        ]
    )

    assert result == ("terminal_output", "en fil jag kan ladda ner")


def test_last_answered_question_is_none_while_awaiting_reply() -> None:
    result = last_answered_question(
        [
            ConversationMessage(
                role="assistant",
                content="Which output?",
                metadata={"question_id": "terminal_output"},
            ),
        ]
    )

    assert result is None


def test_a_question_asked_again_keeps_the_number_it_already_had() -> None:
    # Re-asking after an unusable reply must not make the interview look
    # longer than it is; the user is being asked the same thing again.
    conversation = [
        ConversationMessage(role="user", content="Build a flow."),
        ConversationMessage(
            role="assistant",
            content="Which output?",
            metadata={"question_id": "terminal_output"},
        ),
        ConversationMessage(role="user", content="jag vet inte"),
    ]

    assert question_ordinal_in_session(conversation, question_id="terminal_output") == 1
    assert (
        question_ordinal_in_session(conversation, question_id="post_processing_goal")
        == 2
    )


def test_the_first_question_of_a_session_is_the_first_one() -> None:
    assert (
        question_ordinal_in_session(
            [ConversationMessage(role="user", content="Build a flow.")],
            question_id="terminal_output",
        )
        == 1
    )
