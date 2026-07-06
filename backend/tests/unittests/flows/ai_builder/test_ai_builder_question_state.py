from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_question_state import (
    last_answered_question,
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
