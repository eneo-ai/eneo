"""Per-answer feedback: the request model and the conversation endpoints."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.conversations.conversations_router import (
    delete_message_feedback,
    set_message_feedback,
)
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.questions.question import MESSAGE_FEEDBACK_TEXT_MAX_LENGTH, MessageFeedback
from eneo.sessions.sessions_repo import OwnedChatPartner


class TestMessageFeedbackModel:
    def test_blank_comment_is_stored_as_none(self):
        assert MessageFeedback(value=1, text="   ").text is None

    def test_comment_is_trimmed(self):
        assert (
            MessageFeedback(value=-1, text="  Fel paragraf \n").text == "Fel paragraf"
        )

    def test_rejects_a_comment_over_the_limit(self):
        with pytest.raises(ValidationError):
            MessageFeedback(value=1, text="x" * (MESSAGE_FEEDBACK_TEXT_MAX_LENGTH + 1))

    @pytest.mark.parametrize("value", [0, 2, -2])
    def test_rejects_values_other_than_up_and_down(self, value: int):
        with pytest.raises(ValidationError):
            MessageFeedback.model_validate({"value": value})


def _container(partner: OwnedChatPartner | None) -> MagicMock:
    container = MagicMock()
    session_service = AsyncMock()
    if partner is None:
        session_service.get_message_partner.side_effect = NotFoundException(
            "Message not found."
        )
    else:
        session_service.get_message_partner.return_value = partner
    session_service.set_message_feedback.side_effect = (
        lambda *, session_id, message_id, feedback: feedback
    )
    container.session_service.return_value = session_service
    container.assistant_service.return_value = AsyncMock()
    container.group_chat_service.return_value = AsyncMock()
    return container


class TestSetMessageFeedback:
    async def test_rates_after_authorizing_the_assistant(self):
        assistant_id = uuid4()
        container = _container(OwnedChatPartner(assistant_id, None))
        session_id, message_id = uuid4(), uuid4()

        stored = await set_message_feedback(
            feedback=MessageFeedback(value=1),
            session_id=session_id,
            message_id=message_id,
            container=container,
        )

        assert stored == MessageFeedback(value=1)
        container.assistant_service.return_value.get_assistant.assert_awaited_once_with(
            assistant_id
        )
        container.session_service.return_value.set_message_feedback.assert_awaited_once_with(
            session_id=session_id,
            message_id=message_id,
            feedback=MessageFeedback(value=1),
        )

    async def test_authorizes_a_group_chat_through_the_group_chat(self):
        group_chat_id = uuid4()
        container = _container(OwnedChatPartner(None, group_chat_id))

        await set_message_feedback(
            feedback=MessageFeedback(value=-1),
            session_id=uuid4(),
            message_id=uuid4(),
            container=container,
        )

        container.group_chat_service.return_value.get_group_chat.assert_awaited_once_with(
            group_chat_id=group_chat_id
        )
        container.assistant_service.return_value.get_assistant.assert_not_awaited()

    async def test_does_not_rate_when_access_to_the_assistant_was_revoked(self):
        container = _container(OwnedChatPartner(uuid4(), None))
        container.assistant_service.return_value.get_assistant.side_effect = (
            UnauthorizedException("revoked")
        )

        with pytest.raises(UnauthorizedException):
            await set_message_feedback(
                feedback=MessageFeedback(value=1),
                session_id=uuid4(),
                message_id=uuid4(),
                container=container,
            )

        container.session_service.return_value.set_message_feedback.assert_not_awaited()

    async def test_does_not_rate_another_principals_message(self):
        container = _container(None)

        with pytest.raises(NotFoundException):
            await set_message_feedback(
                feedback=MessageFeedback(value=1),
                session_id=uuid4(),
                message_id=uuid4(),
                container=container,
            )

        container.assistant_service.return_value.get_assistant.assert_not_awaited()
        container.session_service.return_value.set_message_feedback.assert_not_awaited()


class TestDeleteMessageFeedback:
    async def test_clears_after_authorizing_the_assistant(self):
        container = _container(OwnedChatPartner(uuid4(), None))
        session_id, message_id = uuid4(), uuid4()

        await delete_message_feedback(
            session_id=session_id, message_id=message_id, container=container
        )

        container.session_service.return_value.clear_message_feedback.assert_awaited_once_with(
            session_id=session_id, message_id=message_id
        )

    async def test_does_not_clear_another_principals_message(self):
        container = _container(None)

        with pytest.raises(NotFoundException):
            await delete_message_feedback(
                session_id=uuid4(), message_id=uuid4(), container=container
            )

        container.session_service.return_value.clear_message_feedback.assert_not_awaited()
