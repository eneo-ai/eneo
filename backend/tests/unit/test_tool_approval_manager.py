from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import intric.mcp_servers.infrastructure.tool_approval as tool_approval_module
from intric.mcp_servers.infrastructure.tool_approval import (
    ToolApprovalDecision,
    ToolApprovalManager,
)


@pytest.mark.asyncio
async def test_tool_approval_lifecycle_accept_then_wait():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1", "tool-2"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    wait_task = asyncio.create_task(manager.wait_for_approval(approval_id, timeout=1.0))

    partial = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert partial.status == "accepted"
    assert partial.decisions_received == 1
    assert partial.decisions_remaining == 1

    final = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-2", approved=False)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert final.status == "accepted"
    assert final.decisions_received == 2
    assert final.decisions_remaining == 0

    wait_result = await wait_task
    assert wait_result.timed_out is False
    assert wait_result.cancelled is False
    by_id = {d.tool_call_id: d for d in wait_result.decisions}
    assert by_id["tool-1"].approved is True
    assert by_id["tool-2"].approved is False


@pytest.mark.asyncio
async def test_tool_approval_submit_idempotent_and_conflicting_replay():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    first = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=False)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert first.status == "accepted"
    assert first.response_status == "accepted"

    replay_same = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=False)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert replay_same.status == "accepted"
    assert replay_same.response_status == "already_processed"

    replay_conflict = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert replay_conflict.status == "conflict"

    await manager.wait_for_approval(approval_id, timeout=0.1)


@pytest.mark.asyncio
async def test_tool_approval_rejects_wrong_actor_context():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    forbidden = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
        actor_tenant_id=tenant_id,
        actor_user_id=uuid4(),
    )
    assert forbidden.status == "forbidden"


@pytest.mark.asyncio
async def test_tool_approval_reports_unrecognized_tool_ids_and_processes_valid_ids():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1", "tool-2"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    result = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[
            ToolApprovalDecision(tool_call_id="tool-1", approved=True),
            ToolApprovalDecision(tool_call_id="tool-999", approved=False),
        ],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert result.status == "accepted"
    assert result.decisions_received == 1
    assert result.decisions_remaining == 1
    assert result.unrecognized_tool_call_ids == ["tool-999"]

    await manager.cancel_approval(approval_id)


@pytest.mark.asyncio
async def test_tool_approval_timeout_denies_all_tools():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    result = await manager.wait_for_approval(
        approval_id=approval_id, timeout=0.01, poll_interval=0.005
    )
    assert result.timed_out is True
    assert result.cancelled is False
    assert len(result.decisions) == 1
    assert result.decisions[0].approved is False
    assert result.decisions[0].reason == "timeout"

    not_found = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert not_found.status == "not_found"


@pytest.mark.asyncio
async def test_tool_approval_cancel_unblocks_waiter():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1", "tool-2"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    wait_task = asyncio.create_task(manager.wait_for_approval(approval_id, timeout=1.0))
    cancelled = await manager.cancel_approval(approval_id)
    assert cancelled is True

    result = await wait_task
    assert result.cancelled is True
    assert result.timed_out is False
    assert {d.approved for d in result.decisions} == {False}


@pytest.mark.asyncio
async def test_get_approval_context_returns_context_for_valid_actor():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    assistant_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        assistant_id=assistant_id,
    )

    context_result = await manager.get_approval_context(
        approval_id=approval_id,
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert context_result.status == "ok"
    assert context_result.context is not None
    assert context_result.context.session_id == session_id
    assert context_result.context.assistant_id == assistant_id
    assert context_result.context.tenant_id == tenant_id
    assert context_result.context.user_id == user_id

    await manager.cancel_approval(approval_id)


@pytest.mark.asyncio
async def test_get_approval_context_rejects_wrong_user():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=uuid4(),
    )

    context_result = await manager.get_approval_context(
        approval_id=approval_id,
        actor_tenant_id=tenant_id,
        actor_user_id=uuid4(),
    )
    assert context_result.status == "forbidden"
    assert context_result.context is None

    await manager.cancel_approval(approval_id)


@pytest.mark.asyncio
async def test_get_approval_context_rejects_wrong_tenant():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=uuid4(),
    )

    context_result = await manager.get_approval_context(
        approval_id=approval_id,
        actor_tenant_id=uuid4(),
        actor_user_id=user_id,
    )
    assert context_result.status == "forbidden"
    assert context_result.context is None

    await manager.cancel_approval(approval_id)


@pytest.mark.asyncio
async def test_get_approval_context_returns_not_found_for_expired_id(monkeypatch):
    monkeypatch.setattr(tool_approval_module, "APPROVAL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(tool_approval_module, "APPROVAL_TTL_SECONDS", 1)

    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    # Use default timeout path to ensure module constant monkeypatch is respected.
    wait_result = await manager.wait_for_approval(approval_id=approval_id)
    assert wait_result.timed_out is True

    context_result = await manager.get_approval_context(
        approval_id=approval_id,
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert context_result.status == "not_found"
    assert context_result.context is None


@pytest.mark.asyncio
async def test_concurrent_cancel_and_submit_does_not_deadlock():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=uuid4(),
    )

    submit_task = asyncio.create_task(
        manager.submit_decision(
            approval_id=approval_id,
            decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
            actor_tenant_id=tenant_id,
            actor_user_id=user_id,
        )
    )
    cancel_task = asyncio.create_task(manager.cancel_approval(approval_id))

    submit_result, cancelled = await asyncio.wait_for(
        asyncio.gather(submit_task, cancel_task),
        timeout=1.0,
    )
    assert submit_result.status in {"accepted", "not_found", "conflict"}
    assert isinstance(cancelled, bool)


@pytest.mark.asyncio
async def test_submit_after_timeout_returns_not_found(monkeypatch):
    monkeypatch.setattr(tool_approval_module, "APPROVAL_TIMEOUT_SECONDS", 0.01)

    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=uuid4(),
    )

    timed_out = await manager.wait_for_approval(approval_id=approval_id)
    assert timed_out.timed_out is True

    submit_result = await manager.submit_decision(
        approval_id=approval_id,
        decisions=[ToolApprovalDecision(tool_call_id="tool-1", approved=True)],
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    assert submit_result.status == "not_found"


@pytest.mark.asyncio
async def test_request_approval_uses_namespaced_redis_key_and_ttl():
    redis_client = AsyncMock()
    manager = ToolApprovalManager(redis_client=redis_client)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()

    await manager.request_approval(
        approval_id=approval_id,
        tool_call_ids=["tool-1"],
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
    )

    redis_client.set.assert_awaited_once()
    args = redis_client.set.await_args.args
    kwargs = redis_client.set.await_args.kwargs

    redis_key = args[0]
    payload = json.loads(args[1])
    assert redis_key.startswith(f"intric:{tool_approval_module.get_settings().environment}:mcp:approval:")
    assert redis_key.endswith(f":{approval_id}")
    assert kwargs["ex"] == tool_approval_module.APPROVAL_TTL_SECONDS

    assert payload["approval_id"] == approval_id
    assert payload["context"]["tenant_id"] == str(tenant_id)
    assert payload["context"]["user_id"] == str(user_id)
    assert payload["context"]["session_id"] == str(session_id)


def test_denial_reason_sanitization_resists_xss_like_payloads():
    corpus = [
        "<script>alert(1)</script>",
        "`rm -rf /`",
        "normal reason with markdown **bold** and _italics_",
        "payload with \x00control\x1f chars",
        "<b>delete this</b>",
    ]

    for raw_reason in corpus:
        decision = ToolApprovalDecision(
            tool_call_id="tool-1",
            approved=False,
            reason=raw_reason,
        )
        assert decision.reason is not None
        assert len(decision.reason) <= tool_approval_module.MAX_DENIAL_REASON_LENGTH
        assert "<" not in decision.reason
        assert ">" not in decision.reason
        assert "`" not in decision.reason
        assert "*" not in decision.reason

    with pytest.raises(ValueError, match="reason is only allowed when approved=false"):
        ToolApprovalDecision(tool_call_id="tool-1", approved=True, reason="not allowed")


@pytest.mark.asyncio
async def test_malformed_context_payload_returns_not_found():
    manager = ToolApprovalManager(redis_client=None)
    approval_id = str(uuid4())
    tenant_id = uuid4()
    user_id = uuid4()
    
    # Manually inject malformed state to simulate corruption or schema mismatch
    # Has valid auth fields (passes _context_matches) but missing required session_id
    malformed_payload = {
        "context": {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            # Missing session_id -> causes KeyError in get_approval_context
        },
        "tool_call_ids": ["tool-1"],
    }
    await manager._save_state(approval_id, malformed_payload)

    # Should not raise KeyError but return not_found and log warning
    result = await manager.get_approval_context(
        approval_id=approval_id,
        actor_tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    
    assert result.status == "not_found"
    assert result.context is None

    await manager._delete_state(approval_id)
