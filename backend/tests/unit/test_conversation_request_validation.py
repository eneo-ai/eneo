from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.conversations.conversation_models import ConversationRequest, PreflightRequest


def test_conversation_request_requires_exactly_one_target_id():
    assistant_id = uuid4()
    session_id = uuid4()

    with pytest.raises(ValueError, match="exactly one"):
        ConversationRequest(question="hello")

    with pytest.raises(ValueError, match="not multiple"):
        ConversationRequest(
            question="hello",
            assistant_id=assistant_id,
            session_id=session_id,
        )


def test_conversation_request_accepts_single_target_id():
    assistant_id = uuid4()

    request = ConversationRequest(
        question="hello",
        assistant_id=assistant_id,
    )

    assert request.assistant_id == assistant_id
    assert request.session_id is None
    assert request.group_chat_id is None


def test_conversation_request_accepts_request_scoped_personal_model():
    model_id = uuid4()
    request = ConversationRequest(
        question="hello",
        assistant_id=uuid4(),
        settings={"completion_model_id": model_id},
    )

    assert request.settings.completion_model_id == model_id


@pytest.mark.parametrize("request_type", [ConversationRequest, PreflightRequest])
def test_existing_choices_must_use_the_versioned_settings_endpoint(request_type):
    with pytest.raises(ValueError, match="settings endpoint"):
        request_type(question="hello", session_id=uuid4(), settings={})
    with pytest.raises(ValueError, match="existing conversation"):
        request_type(question="hello", assistant_id=uuid4(), settings_revision=1)
