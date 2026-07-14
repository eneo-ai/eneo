"""Unit tests for the logging endpoint's session-scoped authorization.

The invariant: a message's logging details are readable only by the owner of
the session it belongs to, or by a user with insight access to that session's
assistant/group chat. Everything else — unknown message, service question
without a session, foreign session — collapses to 404 so the endpoint never
leaks message existence.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.logging.logging_router import get_logging_details
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)


def _container(
    question,
    owner_error: Exception | None = None,
    insight_error: Exception | None = None,
):
    question_repo = SimpleNamespace(get=AsyncMock(return_value=question))
    session_service = SimpleNamespace(
        get_session_by_uuid=AsyncMock(side_effect=owner_error, return_value=MagicMock())
    )
    analysis_service = SimpleNamespace(
        get_insight_session=AsyncMock(
            side_effect=insight_error, return_value=MagicMock()
        )
    )
    return SimpleNamespace(
        question_repo=lambda: question_repo,
        session_service=lambda: session_service,
        analysis_service=lambda: analysis_service,
    )


def _question(session_id=None, logging_details="captured"):
    return SimpleNamespace(session_id=session_id, logging_details=logging_details)


SENTINEL = object()


def _patched_protocol():
    return patch(
        "eneo.logging.logging_router.to_question_logging", return_value=SENTINEL
    )


class TestLoggingEndpointAuthz:
    @pytest.mark.asyncio
    async def test_unknown_message_is_404(self):
        with pytest.raises(NotFoundException):
            await get_logging_details(uuid4(), container=_container(question=None))

    @pytest.mark.asyncio
    async def test_service_question_without_session_is_404(self):
        question = _question(session_id=None)

        with pytest.raises(NotFoundException):
            await get_logging_details(uuid4(), container=_container(question))

    @pytest.mark.asyncio
    async def test_session_owner_can_read(self):
        question = _question(session_id=uuid4())

        with _patched_protocol():
            result = await get_logging_details(uuid4(), container=_container(question))

        assert result is SENTINEL

    @pytest.mark.asyncio
    async def test_insight_access_reads_via_fallback(self):
        question = _question(session_id=uuid4())
        container = _container(question, owner_error=UnauthorizedException("not owner"))

        with _patched_protocol():
            result = await get_logging_details(uuid4(), container=container)

        assert result is SENTINEL
        assert container.analysis_service().get_insight_session.await_count == 1

    @pytest.mark.asyncio
    async def test_foreign_session_collapses_to_404(self):
        question = _question(session_id=uuid4())
        container = _container(
            question,
            owner_error=UnauthorizedException("not owner"),
            insight_error=UnauthorizedException("no insight access"),
        )

        with pytest.raises(NotFoundException):
            await get_logging_details(uuid4(), container=container)

    @pytest.mark.asyncio
    async def test_uncaptured_message_is_400_for_authorized_reader(self):
        question = _question(session_id=uuid4(), logging_details=None)

        with pytest.raises(BadRequestException):
            await get_logging_details(uuid4(), container=_container(question))
