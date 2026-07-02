from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_question_state import (
    derive_asked_question_state,
    last_answered_question,
)


def test_derive_asked_question_state_tracks_v2_question_specific_evidence() -> None:
    state = derive_asked_question_state(
        [
            ConversationMessage(role="user", content="Build a flow."),
            ConversationMessage(
                role="assistant",
                content="Which metadata fields are needed?",
                metadata={"question_id": "runtime_metadata_fields"},
            ),
            ConversationMessage(
                role="user",
                content="Diarienummer och avdelning.",
            ),
        ]
    )

    assert state.asked_question_ids == frozenset({"runtime_metadata_fields"})
    assert state.question_ids_with_new_evidence == frozenset(
        {"runtime_metadata_fields"}
    )
    assert state.has_new_evidence is True


def test_derive_asked_question_state_resets_evidence_after_question_is_reasked() -> (
    None
):
    state = derive_asked_question_state(
        [
            ConversationMessage(role="user", content="Build a flow."),
            ConversationMessage(
                role="assistant",
                content="Which metadata fields are needed?",
                metadata={"question_id": "runtime_metadata_fields"},
            ),
            ConversationMessage(role="user", content="Diarienummer och avdelning."),
            ConversationMessage(
                role="assistant",
                content="Which metadata fields are needed?",
                metadata={"question_id": "runtime_metadata_fields"},
            ),
        ]
    )

    assert state.asked_question_ids == frozenset({"runtime_metadata_fields"})
    assert state.question_ids_with_new_evidence == frozenset()
    assert state.has_new_evidence is False


def test_question_id_counts_track_repeated_asks_across_evidence() -> None:
    state = derive_asked_question_state(
        [
            ConversationMessage(role="user", content="Build a flow."),
            ConversationMessage(
                role="assistant",
                content="Which input?",
                metadata={"question_id": "primary_runtime_input"},
            ),
            ConversationMessage(role="user", content="A document."),
            ConversationMessage(
                role="assistant",
                content="Which input, exactly?",
                metadata={"question_id": "primary_runtime_input"},
            ),
            ConversationMessage(role="user", content="Not sure."),
        ]
    )

    # The count survives the intervening evidence turn (only the evidence set resets).
    assert state.question_id_counts["primary_runtime_input"] == 2
    assert state.question_ids_with_new_evidence == frozenset({"primary_runtime_input"})


def test_question_id_counts_is_empty_when_no_question_asked() -> None:
    state = derive_asked_question_state(
        [ConversationMessage(role="user", content="Build a flow.")]
    )

    assert dict(state.question_id_counts) == {}


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
