from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    compact_ai_builder_conversation,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
    metadata_for_assistant_question,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_question_state import (
    last_answered_question,
    question_ordinal_in_session,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
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


def _ask(conversation: list[ConversationMessage], question_id: str) -> None:
    """Append a question turn the way the Builder persists one.

    The number is read off the conversation and stamped onto the message, which
    is what dispatch and question persistence do together.
    """

    question = StructuredQuestionPayload(
        question_id=question_id,
        question=f"Question about {question_id}?",
        options=[StructuredQuestionOptionPayload(id="a", label="A", value="a")],
        selection_mode="single",
        allow_custom=False,
        question_index=question_ordinal_in_session(
            conversation, question_id=question_id
        ),
    )
    tool_call_id = f"call_{len(conversation)}"
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=question.question,
            metadata=metadata_for_assistant_question(question),
            tool_calls=[
                make_persisted_assistant_tool_call(
                    tool_call_id=tool_call_id,
                    tool_name=ASK_STRUCTURED_QUESTION_TOOL_NAME,
                    arguments=question.model_dump(mode="json"),
                ).model_dump(mode="json")
            ],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content="Question presented to user.",
            tool_call_id=tool_call_id,
        )
    )


def _answer(conversation: list[ConversationMessage], question_id: str) -> None:
    conversation.append(
        ConversationMessage(
            role="user",
            content="jag vet inte",
            metadata={"question_response": {"question_id": question_id}},
        )
    )


def test_a_number_the_user_has_seen_survives_compaction() -> None:
    # Compaction keeps the latest interaction of a re-asked question, so
    # counting positions afterwards would renumber a question the user has
    # already been shown a number for.
    conversation = [ConversationMessage(role="user", content="Build a flow.")]
    _ask(conversation, "terminal_output")
    _answer(conversation, "terminal_output")
    _ask(conversation, "post_processing_goal")
    _answer(conversation, "post_processing_goal")
    _ask(conversation, "terminal_output")

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=6,
        tail_messages=2,
    )

    assert [
        message.metadata for message in compacted if message.role == "assistant"
    ] != [message.metadata for message in conversation if message.role == "assistant"]
    assert question_ordinal_in_session(compacted, question_id="terminal_output") == 1
    assert (
        question_ordinal_in_session(compacted, question_id="post_processing_goal") == 2
    )
    assert (
        question_ordinal_in_session(compacted, question_id="primary_runtime_input") == 3
    )
