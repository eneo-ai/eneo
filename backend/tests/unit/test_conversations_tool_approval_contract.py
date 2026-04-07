from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4, UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from intric.assistants.api.assistant_models import AskAssistant
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.rate_limiting import (
    RateLimitExceededError,
    RateLimitResult,
)
from intric.conversations.conversations_router import approve_tools
from intric.mcp_servers.infrastructure.tool_approval import (
    ToolApprovalContext,
    ToolApprovalContextLookupResult,
    ToolApprovalDecision,
    ToolApprovalSubmitResult,
)


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/conversations/approve-tools/",
            "headers": [],
        }
    )


def _make_container():
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="tester",
        email="tester@example.com",
    )
    audit_service = AsyncMock()
    container = SimpleNamespace(
        user=lambda: user,
        redis_client=lambda: AsyncMock(),
        audit_service=lambda: audit_service,
    )
    return container, user, audit_service


def _make_context(user, assistant_id=None) -> ToolApprovalContext:
    return ToolApprovalContext(
        approval_id=str(uuid4()),
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=uuid4(),
        assistant_id=assistant_id or uuid4(),
    )


@pytest.mark.asyncio
async def test_approve_tools_returns_accepted_payload_shape():
    container, user, _ = _make_container()
    context = _make_context(user)
    decision = ToolApprovalDecision(tool_call_id="call_1", approved=True)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="accepted",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        response = await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )

    mock_validate_scope.assert_awaited_once()

    payload = response.model_dump()
    assert payload["status"] == "accepted"
    assert payload["approval_id"] == context.approval_id
    assert payload["decisions_received"] == 1
    assert payload["decisions_remaining"] == 0
    assert payload["unrecognized_tool_call_ids"] == []


@pytest.mark.asyncio
async def test_approve_tools_returns_already_processed_payload_shape():
    container, user, audit_service = _make_container()
    context = _make_context(user)
    decision = ToolApprovalDecision(tool_call_id="call_1", approved=False)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="already_processed",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        response = await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )

    mock_validate_scope.assert_awaited_once()

    payload = response.model_dump()
    assert payload["status"] == "already_processed"
    assert payload["approval_id"] == context.approval_id


@pytest.mark.asyncio
async def test_approve_tools_returns_404_payload_shape():
    container, _, _ = _make_container()
    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="not_found"
    )

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await approve_tools(
                http_request=_make_request(),
                approval_id=uuid4(),
                decisions=[],
                container=container,
            )

    assert exc_info.value.status_code == 404
    assert "expired" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_approve_tools_returns_409_payload_shape():
    container, user, _ = _make_container()
    context = _make_context(user)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="conflict",
        existing_status="accepted",
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await approve_tools(
                http_request=_make_request(),
                approval_id=UUID(context.approval_id),
                decisions=[],
                container=container,
            )

    mock_validate_scope.assert_awaited_once()

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "approval_conflict"
    assert detail["existing_status"] == "accepted"


@pytest.mark.asyncio
async def test_approve_tools_returns_429_payload_shape_with_retry_after():
    container, user, _ = _make_container()
    rate_limit_result = RateLimitResult(
        allowed=False,
        current_count=21,
        max_requests=20,
        window_seconds=60,
    )

    with patch(
        "intric.conversations.conversations_router.enforce_rate_limit",
        side_effect=RateLimitExceededError(rate_limit_result),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await approve_tools(
                http_request=_make_request(),
                approval_id=uuid4(),
                decisions=[],
                container=container,
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Retry-After"] == "60"
    detail = exc_info.value.detail
    assert detail["code"] == "rate_limit_exceeded"
    assert detail["retry_after_seconds"] == 60


@pytest.mark.asyncio
async def test_approve_tools_success_creates_audit_log_entry():
    container, user, audit_service = _make_container()
    context = _make_context(user)
    decision = ToolApprovalDecision(tool_call_id="call_1", approved=True)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="accepted",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )
    
    mock_validate_scope.assert_awaited_once()

    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.TOOL_APPROVAL_SUBMITTED
    assert kwargs["entity_id"] == context.assistant_id
    assert kwargs["entity_type"] == EntityType.ASSISTANT
    assert kwargs["metadata"]["extra"]["approved_count"] == 1
    assert kwargs["metadata"]["extra"]["denied_count"] == 0


@pytest.mark.asyncio
async def test_approve_tools_denial_creates_audit_log_entry():
    container, user, audit_service = _make_container()
    context = _make_context(user)
    decision = ToolApprovalDecision(
        tool_call_id="call_1",
        approved=False,
        reason="Do not execute destructive action",
    )

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="accepted",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )

    mock_validate_scope.assert_awaited_once()

    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.TOOL_APPROVAL_SUBMITTED
    assert kwargs["metadata"]["extra"]["approved_count"] == 0
    assert kwargs["metadata"]["extra"]["denied_count"] == 1


@pytest.mark.asyncio
async def test_approve_tools_skip_audit_log_on_replay():
    container, user, audit_service = _make_container()
    context = _make_context(user)
    decision = ToolApprovalDecision(tool_call_id="call_1", approved=True)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="already_processed",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )

    mock_validate_scope.assert_awaited_once()
    audit_service.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_tools_session_entity_type():
    container, user, audit_service = _make_container()
    # Create context without assistant_id (None)
    context = ToolApprovalContext(
        approval_id=str(uuid4()),
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=uuid4(),
        assistant_id=None,
    )
    decision = ToolApprovalDecision(tool_call_id="call_1", approved=True)

    manager = AsyncMock()
    manager.get_approval_context.return_value = ToolApprovalContextLookupResult(
        status="ok", context=context
    )
    manager.submit_decision.return_value = ToolApprovalSubmitResult(
        status="accepted",
        response_status="accepted",
        decisions_received=1,
        decisions_remaining=0,
        unrecognized_tool_call_ids=[],
    )

    mock_validate_scope = AsyncMock()

    with (
        patch(
            "intric.conversations.conversations_router.enforce_rate_limit",
            new=AsyncMock(),
        ),
        patch(
            "intric.conversations.conversations_router.get_approval_manager",
            return_value=manager,
        ),
        patch(
            "intric.conversations.conversations_router._validate_conversation_scope",
            new=mock_validate_scope,
        ),
    ):
        await approve_tools(
            http_request=_make_request(),
            approval_id=UUID(context.approval_id),
            decisions=[decision],
            container=container,
        )

    mock_validate_scope.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["entity_type"] == EntityType.SESSION
    assert kwargs["entity_id"] == context.session_id


def test_legacy_assistant_ask_ignores_require_tool_approval_extra_field():
    ask = AskAssistant.model_validate(
        {
            "question": "hello",
            "require_tool_approval": True,
            "stream": True,
        }
    )
    assert ask.question == "hello"
    assert ask.stream is True
    assert not hasattr(ask, "require_tool_approval")
