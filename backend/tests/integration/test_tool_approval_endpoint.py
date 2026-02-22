from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from intric.audit.infrastructure.rate_limiting import RateLimitServiceUnavailableError
from intric.mcp_servers.infrastructure.tool_approval import get_approval_manager


async def _create_space(client, bearer_token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"approval-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_assistant(client, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        "/api/v1/assistants/",
        json={"name": f"approval-assistant-{uuid4().hex[:8]}", "space_id": space_id},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_app(client, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"approval-app-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    if response.status_code == 400 and "No transcription model available" in response.text:
        pytest.skip("App creation requires a transcription model in this test environment.")
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_scoped_key(
    client,
    bearer_token: str,
    *,
    scope_type: str,
    scope_id: str | None,
) -> str:
    payload = {
        "name": f"approval-key-{scope_type}-{uuid4().hex[:6]}",
        "key_type": "sk_",
        "permission": "write",
        "scope_type": scope_type,
        "scope_id": scope_id,
    }
    response = await client.post(
        "/api/v1/api-keys",
        json=payload,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


async def _create_session_for_assistant(db_container, assistant_id: str) -> UUID:
    async with db_container() as container:
        session_service = container.session_service()
        session = await session_service.create_session(
            name=f"approval-session-{uuid4().hex[:8]}",
            assistant_id=UUID(assistant_id),
        )
    return session.id


async def _seed_approval_context(redis_client, *, user_id, tenant_id, session_id, assistant_id):
    manager = get_approval_manager(redis_client=redis_client)
    approval_id = str(uuid4())
    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["call_1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        assistant_id=assistant_id,
    )
    return manager, approval_id


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_scoped_key_cannot_approve_other_assistant_context(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
):
    space_id = await _create_space(client, default_user_token)
    assistant_a = await _create_assistant(client, default_user_token, space_id)
    assistant_b = await _create_assistant(client, default_user_token, space_id)
    session_id = await _create_session_for_assistant(db_container, assistant_b)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_b),
    )

    scoped_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="assistant",
        scope_id=assistant_a,
    )

    try:
        response = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": scoped_key},
        )
        assert response.status_code == 403, response.text
        body = response.json()
        code = body.get("code") or body.get("detail", {}).get("code")
        assert code == "insufficient_scope"
    finally:
        await manager.cancel_approval(approval_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_approve_tools_outside_space(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
):
    space_a = await _create_space(client, default_user_token)
    space_b = await _create_space(client, default_user_token)
    assistant_b = await _create_assistant(client, default_user_token, space_b)
    session_id = await _create_session_for_assistant(db_container, assistant_b)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_b),
    )

    scoped_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="space",
        scope_id=space_a,
    )

    try:
        response = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": scoped_key},
        )
        assert response.status_code == 403, response.text
        body = response.json()
        code = body.get("code") or body.get("detail", {}).get("code")
        assert code == "insufficient_scope"
    finally:
        await manager.cancel_approval(approval_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_scoped_key_blocked_from_approve_tools(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
):
    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)
    app_id = await _create_app(client, default_user_token, space_id)
    session_id = await _create_session_for_assistant(db_container, assistant_id)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_id),
    )

    scoped_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="app",
        scope_id=app_id,
    )

    try:
        response = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": scoped_key},
        )
        assert response.status_code == 403, response.text
        body = response.json()
        code = body.get("code") or body.get("detail", {}).get("code")
        assert code == "insufficient_scope"
    finally:
        await manager.cancel_approval(approval_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_tools_succeeds_when_rate_limiter_unavailable(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
    monkeypatch,
):
    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)
    session_id = await _create_session_for_assistant(db_container, assistant_id)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_id),
    )

    tenant_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="tenant",
        scope_id=None,
    )

    async def _failing_rate_limit(*args, **kwargs):
        raise RateLimitServiceUnavailableError(Exception("redis down"))

    monkeypatch.setattr(
        "intric.conversations.conversations_router.enforce_rate_limit",
        _failing_rate_limit,
    )

    response = await client.post(
        f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
        json=[{"tool_call_id": "call_1", "approved": True}],
        headers={"X-API-Key": tenant_key},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] in {"accepted", "already_processed"}
    assert payload["approval_id"] == approval_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_tools_replay_idempotent_then_conflict_with_real_redis(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
):
    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)
    session_id = await _create_session_for_assistant(db_container, assistant_id)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_id),
    )

    tenant_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="tenant",
        scope_id=None,
    )

    try:
        first = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": tenant_key},
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "accepted"

        replay = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": tenant_key},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["status"] == "already_processed"

        conflict = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": False}],
            headers={"X-API-Key": tenant_key},
        )
        assert conflict.status_code == 409, conflict.text
        body = conflict.json()
        detail = body.get("detail", body)
        assert detail["code"] == "approval_conflict"
    finally:
        await manager.cancel_approval(approval_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_tools_returns_404_after_approval_state_expires(
    client,
    db_container,
    redis_client,
    default_user,
    default_user_token,
):
    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)
    session_id = await _create_session_for_assistant(db_container, assistant_id)

    manager, approval_id = await _seed_approval_context(
        redis_client,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        session_id=session_id,
        assistant_id=UUID(assistant_id),
    )
    tenant_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="tenant",
        scope_id=None,
    )
    redis_key = manager._key(approval_id)

    try:
        await redis_client.expire(redis_key, 1)
        await asyncio.sleep(1.2)

        response = await client.post(
            f"/api/v1/conversations/approve-tools/?approval_id={approval_id}",
            json=[{"tool_call_id": "call_1", "approved": True}],
            headers={"X-API-Key": tenant_key},
        )
        assert response.status_code == 404, response.text
    finally:
        # Ensure no stale in-memory event remains in the process singleton.
        manager._pending_events.pop(approval_id, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_flow_fails_closed_when_redis_unavailable_mid_approval(
    client,
    default_user_token,
):
    tenant_key = await _create_scoped_key(
        client,
        default_user_token,
        scope_type="tenant",
        scope_id=None,
    )

    failing_manager = AsyncMock()
    failing_manager.get_approval_context.side_effect = ConnectionError("redis unavailable")

    with patch(
        "intric.conversations.conversations_router.get_approval_manager",
        return_value=failing_manager,
    ):
        with pytest.raises(ConnectionError):
            await client.post(
                f"/api/v1/conversations/approve-tools/?approval_id={uuid4()}",
                json=[{"tool_call_id": "call_1", "approved": True}],
                headers={"X-API-Key": tenant_key},
            )
