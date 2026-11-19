"""Request validation of the insights chat endpoints."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.analysis.insight_chat_models import (
    InsightChatContinueRequest,
    InsightChatStartRequest,
    InsightSelectedRange,
)


def test_exactly_one_target_is_required():
    with pytest.raises(ValidationError, match="exactly one"):
        InsightChatStartRequest(question="q")
    with pytest.raises(ValidationError, match="exactly one"):
        InsightChatStartRequest(
            question="q", assistant_id=uuid4(), group_chat_id=uuid4()
        )


def test_defaults():
    request = InsightChatStartRequest(question="q", group_chat_id=uuid4())

    assert request.timezone == "UTC"
    assert request.stream is True
    assert request.selected_range is None


def test_every_answer_is_streamed():
    """The answer is always the chat's streamed format; asking for a single
    JSON answer is refused."""
    with pytest.raises(ValidationError):
        InsightChatStartRequest(question="q", assistant_id=uuid4(), stream=False)
    with pytest.raises(ValidationError):
        InsightChatContinueRequest(question="q", stream=False)
    assert InsightChatContinueRequest(question="q", stream=True).stream is True


def test_question_must_not_be_empty():
    with pytest.raises(ValidationError):
        InsightChatStartRequest(question="", assistant_id=uuid4())
    with pytest.raises(ValidationError):
        InsightChatContinueRequest(question="")


def test_selected_range_must_be_ordered():
    with pytest.raises(ValidationError, match="not be before"):
        InsightSelectedRange(start=date(2026, 9, 8), end=date(2026, 9, 1))
    assert InsightSelectedRange(start=date(2026, 9, 1), end=date(2026, 9, 1))
