from __future__ import annotations

from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_question_state import (
    derive_asked_question_state,
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
