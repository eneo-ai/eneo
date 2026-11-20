from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from eneo.conversations.conversation_models import ConversationRequest
from eneo.conversations.conversations_router import chat


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
    assert request.retired_group_chat_id is None


def test_conversation_request_keeps_a_retired_group_chat_target_for_the_router():
    """group_chat_id alone is not a 422: the router answers it with 410."""
    group_chat_id = uuid4()

    request = ConversationRequest(question="hello", group_chat_id=group_chat_id)

    assert request.retired_group_chat_id == group_chat_id
    assert request.assistant_id is None


async def test_chat_answers_410_group_chats_retired_for_a_group_chat_id():
    request = ConversationRequest(question="hello", group_chat_id=uuid4())
    container = MagicMock()

    with pytest.raises(HTTPException) as excinfo:
        await chat(
            request=request,
            http_request=SimpleNamespace(),  # pyright: ignore[reportArgumentType]
            container=container,
        )

    assert excinfo.value.status_code == 410
    assert excinfo.value.detail == {
        "code": "group_chats_retired",
        "message": (
            "Group chats were replaced by assistants with specialists. The group "
            "became an assistant with the same id; use assistant_id."
        ),
    }
    container.conversation_service.assert_not_called()
