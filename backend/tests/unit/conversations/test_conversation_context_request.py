"""Limits on the context a client may send with a question."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.conversations.application.conversation_service import ConversationService
from eneo.conversations.conversation_models import (
    ConversationRequest,
    PreflightRequest,
)
from eneo.conversations.question_quote import QuestionContext
from eneo.main.exceptions import BadRequestException


def _request(context: object, model=ConversationRequest):
    return model.model_validate(
        {"assistant_id": str(uuid4()), "question": "Hej", "context": context}
    )


@pytest.mark.parametrize("model", [ConversationRequest, PreflightRequest])
def test_context_is_optional_and_empty_by_default(model):
    request = model.model_validate({"assistant_id": str(uuid4()), "question": "Hej"})

    assert request.context == []


@pytest.mark.parametrize("model", [ConversationRequest, PreflightRequest])
def test_accepts_context_at_the_limits(model):
    request = _request([{"label": "l" * 200, "text": "t" * 12_000}] * 8, model=model)

    assert len(request.context) == 8
    assert request.context[0].label == "l" * 200
    assert len(request.context[0].text) == 12_000


@pytest.mark.parametrize("model", [ConversationRequest, PreflightRequest])
@pytest.mark.parametrize(
    "context",
    [
        [{"label": "l", "text": "t"}] * 9,
        [{"label": "l" * 201, "text": "t"}],
        [{"label": "l", "text": "t" * 12_001}],
        [{"label": "", "text": "t"}],
        [{"label": "l", "text": ""}],
        [{"label": "  ", "text": "t"}],
        [{"label": "l", "text": " \n "}],
        [{"label": "l"}],
        [{"text": "t"}],
        ["text"],
    ],
    ids=[
        "too many items",
        "label too long",
        "text too long",
        "empty label",
        "empty text",
        "blank label",
        "blank text",
        "no text",
        "no label",
        "not an object",
    ],
)
def test_rejects_context_outside_the_limits(model, context):
    with pytest.raises(ValidationError):
        _request(context, model=model)


CONTEXT = [QuestionContext(label="Ärende", text="Text")]


def _service(session: object = None) -> ConversationService:
    return ConversationService(
        assistant_service=AsyncMock(),
        group_chat_service=AsyncMock(),
        session_service=AsyncMock(get_session_by_uuid=AsyncMock(return_value=session)),
        completion_service=AsyncMock(),
        space_service=AsyncMock(),
        file_service=AsyncMock(),
    )


async def test_context_goes_to_the_assistant_with_the_question_as_it_was_asked():
    service = _service()
    assistant_id = uuid4()

    await service.ask_conversation(
        question="Hej", assistant_id=assistant_id, context=CONTEXT
    )

    asked = service.assistant_service.ask.await_args.kwargs
    assert (asked["question"], asked["context"]) == ("Hej", CONTEXT)


@pytest.mark.parametrize("continuing", [False, True], ids=["new", "follow-up"])
async def test_context_is_refused_for_a_group_chat(continuing: bool):
    group_chat_id = uuid4()
    service = _service(SimpleNamespace(group_chat_id=group_chat_id, assistant=None))

    with pytest.raises(BadRequestException, match="not supported for group chats"):
        await service.ask_conversation(
            question="Hej",
            context=CONTEXT,
            **(
                {"session_id": uuid4()}
                if continuing
                else {"group_chat_id": group_chat_id}
            ),
        )

    service.group_chat_service.ask_group_chat.assert_not_awaited()
    service.assistant_service.ask.assert_not_awaited()
