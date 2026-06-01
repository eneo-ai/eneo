from __future__ import annotations

from uuid import uuid4

import pytest

from intric.conversations.conversation_models import ConversationRequest


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
