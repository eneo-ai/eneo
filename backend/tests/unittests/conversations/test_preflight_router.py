from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitExceededError,
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.conversations.application.conversation_service import ConversationService
from eneo.conversations.conversation_models import (
    PreflightRequest,
    PreflightResponse,
)
from eneo.conversations.conversations_router import preflight_tokens
from eneo.questions.question import ToolAssistant, UseTools


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/conversations/preflight",
            "headers": [],
        }
    )


def _make_container(*, preflight_result: PreflightResponse):
    """Stub container exposing exactly what `preflight_tokens` reads."""
    db_session = MagicMock()
    db_session.begin = MagicMock()
    db_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db_session.begin.return_value.__aexit__ = AsyncMock(return_value=None)

    service = MagicMock(spec=ConversationService)
    service.preflight_tokens = AsyncMock(return_value=preflight_result)

    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    return (
        SimpleNamespace(
            session=lambda: db_session,
            conversation_service=lambda: service,
            user=lambda: user,
            redis_client=lambda: MagicMock(),
        ),
        service,
    )


def _sample_response(input_tokens: int = 42, file_tokens: int = 7) -> PreflightResponse:
    return PreflightResponse(
        input_tokens=input_tokens,
        file_tokens=file_tokens,
        model_name="gpt-4o",
        context_window=128000,
    )


@pytest.mark.asyncio
async def test_preflight_router_returns_service_result():
    """Router calls scope validation, then service, and returns the response."""
    expected = _sample_response()
    container, service = _make_container(preflight_result=expected)

    request_body = PreflightRequest(question="hello", assistant_id=uuid4())

    mock_validate = AsyncMock()
    with (
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate,
        ),
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
    ):
        result = await preflight_tokens(
            request=request_body,
            http_request=_make_request(),
            container=container,
        )

    assert result is expected
    mock_validate.assert_awaited_once()
    service.preflight_tokens.assert_awaited_once_with(
        question="hello",
        file_ids=[],
        session_id=None,
        assistant_id=request_body.assistant_id,
        group_chat_id=None,
        tool_assistant_id=None,
    )


@pytest.mark.asyncio
async def test_preflight_router_propagates_session_id():
    """When given session_id the router forwards it to the service."""
    container, service = _make_container(preflight_result=_sample_response())

    session_id = uuid4()
    request_body = PreflightRequest(question="hi", session_id=session_id)

    with (
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=AsyncMock(),
        ),
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
    ):
        await preflight_tokens(
            request=request_body,
            http_request=_make_request(),
            container=container,
        )

    call_kwargs = service.preflight_tokens.call_args.kwargs
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["assistant_id"] is None
    assert call_kwargs["group_chat_id"] is None


@pytest.mark.asyncio
async def test_preflight_router_forwards_tool_assistant_id():
    """Mention targets are forwarded so group-chat preflight can use the same model."""
    container, service = _make_container(preflight_result=_sample_response())

    target_id = uuid4()
    request_body = PreflightRequest(
        question="hi",
        group_chat_id=uuid4(),
        tools=UseTools(assistants=[ToolAssistant(id=target_id, handle="target")]),
    )

    with (
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=AsyncMock(),
        ),
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
    ):
        await preflight_tokens(
            request=request_body,
            http_request=_make_request(),
            container=container,
        )

    assert service.preflight_tokens.call_args.kwargs["tool_assistant_id"] == target_id


@pytest.mark.asyncio
async def test_preflight_router_raises_429_on_rate_limit():
    """A breached rate limit surfaces as 429 with a Retry-After header."""
    container, service = _make_container(preflight_result=_sample_response())
    request_body = PreflightRequest(question="hi", assistant_id=uuid4())

    limiter = AsyncMock(
        side_effect=RateLimitExceededError(
            RateLimitResult(
                allowed=False,
                current_count=601,
                max_requests=600,
                window_seconds=60,
            )
        )
    )
    with (
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=limiter,
        ),
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await preflight_tokens(
                request=request_body,
                http_request=_make_request(),
                container=container,
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Retry-After"] == "60"
    service.preflight_tokens.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_router_falls_open_when_limiter_unavailable():
    """If Redis is down the request still proceeds — preflight is non-critical."""
    container, service = _make_container(preflight_result=_sample_response())
    request_body = PreflightRequest(question="hi", assistant_id=uuid4())

    limiter = AsyncMock(
        side_effect=RateLimitServiceUnavailableError(RuntimeError("redis down"))
    )
    with (
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=limiter,
        ),
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=AsyncMock(),
        ),
    ):
        await preflight_tokens(
            request=request_body,
            http_request=_make_request(),
            container=container,
        )

    service.preflight_tokens.assert_awaited_once()


@pytest.mark.asyncio
async def test_preflight_router_propagates_scope_403():
    """When scope validation rejects the request, the 403 propagates."""
    container, service = _make_container(preflight_result=_sample_response())
    request_body = PreflightRequest(question="hi", assistant_id=uuid4())

    scope_denied = AsyncMock(
        side_effect=HTTPException(status_code=403, detail="scope denied")
    )
    with (
        patch(
            "eneo.conversations.conversations_router._validate_conversation_scope",
            new=scope_denied,
        ),
        patch(
            "eneo.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await preflight_tokens(
                request=request_body,
                http_request=_make_request(),
                container=container,
            )

    assert exc_info.value.status_code == 403
    service.preflight_tokens.assert_not_awaited()
