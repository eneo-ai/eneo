from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.logging import logging_router
from eneo.main.exceptions import BadRequestException


async def test_get_logging_details_uses_authorized_analysis_read(monkeypatch):
    message_id = uuid4()
    question = MagicMock(logging_details=MagicMock())
    response = MagicMock()
    analysis_service = AsyncMock()
    analysis_service.get_message_for_insights.return_value = question
    container = MagicMock()
    container.analysis_service.return_value = analysis_service
    monkeypatch.setattr(
        logging_router, "to_question_logging", MagicMock(return_value=response)
    )

    result = await logging_router.get_logging_details(
        message_id=message_id,
        container=container,
    )

    assert result is response
    analysis_service.get_message_for_insights.assert_awaited_once_with(
        message_id=message_id
    )
    logging_router.to_question_logging.assert_called_once_with(question)


async def test_get_logging_details_preserves_unlogged_bad_request():
    message_id = uuid4()
    analysis_service = AsyncMock()
    analysis_service.get_message_for_insights.return_value = MagicMock(
        logging_details=None
    )
    container = MagicMock()
    container.analysis_service.return_value = analysis_service

    with pytest.raises(BadRequestException, match="Question was not logged"):
        await logging_router.get_logging_details(
            message_id=message_id,
            container=container,
        )
