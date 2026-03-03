from __future__ import annotations

from datetime import datetime, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from intric.authentication.auth_dependencies import ScopeFilter
from intric.audit.domain.action_types import ActionType
from intric.flows.flow import Flow, FlowRun, FlowRunStatus
from intric.flows.api.flow_run_router import (
    cancel_flow_run,
    get_flow_run,
    get_flow_run_evidence,
    list_flow_runs,
    redispatch_flow_run,
)
from intric.main.exceptions import NotFoundException


def _flow(space_id):
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=space_id,
        name="Flow",
        description=None,
        created_by_user_id=uuid4(),
        owner_user_id=uuid4(),
        published_version=1,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )


def _run(flow_id, tenant_id, user_id):
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        user_id=user_id,
        tenant_id=tenant_id,
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_container():
    container = MagicMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.user.return_value = user

    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    flow_execution_backend = MagicMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
    container.flow_execution_backend.return_value = flow_execution_backend
    return container


@pytest.mark.asyncio
async def test_list_flow_runs_returns_paginated_items(mock_container, monkeypatch):
    space_id = uuid4()
    flow = _flow(space_id=space_id)
    run = _run(
        flow_id=flow.id,
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_service.return_value.get_flow.return_value = flow
    mock_container.flow_run_service.return_value.list_runs.return_value = [run]
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=space_id))

    request = SimpleNamespace(state=SimpleNamespace())
    result = await list_flow_runs(
        request=request,
        flow_id=flow.id,
        limit=50,
        offset=0,
        container=mock_container,
    )

    assert result["count"] == 1
    assert result["items"][0].id == run.id
    mock_container.flow_run_service.return_value.list_runs.assert_awaited_once_with(
        flow_id=flow.id,
        limit=50,
        offset=0,
    )
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flow_runs_rejects_space_scope_mismatch(mock_container, monkeypatch):
    flow = _flow(space_id=uuid4())
    mock_container.flow_service.return_value.get_flow.return_value = flow
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=uuid4()))

    with pytest.raises(HTTPException) as exc:
        await list_flow_runs(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_id=flow.id,
            container=mock_container,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_list_flow_runs_validates_flow_exists_without_scope_filter(mock_container, monkeypatch):
    flow = _flow(space_id=uuid4())
    run = _run(
        flow_id=flow.id,
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_service.return_value.get_flow.return_value = flow
    mock_container.flow_run_service.return_value.list_runs.return_value = [run]
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    result = await list_flow_runs(
        request=SimpleNamespace(state=SimpleNamespace()),
        flow_id=flow.id,
        limit=10,
        offset=0,
        container=mock_container,
    )

    assert result["count"] == 1
    mock_container.flow_service.return_value.get_flow.assert_awaited_once_with(flow.id)


@pytest.mark.asyncio
async def test_list_flow_runs_raises_not_found_when_flow_missing_without_scope_filter(
    mock_container,
    monkeypatch,
):
    flow_id = uuid4()
    mock_container.flow_service.return_value.get_flow.side_effect = NotFoundException("Flow not found.")
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    with pytest.raises(NotFoundException):
        await list_flow_runs(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_id=flow_id,
            container=mock_container,
        )

    mock_container.flow_run_service.return_value.list_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_flow_run_logs_audit_entry(mock_container, monkeypatch):
    run_before_cancel = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    cancelled_run = run_before_cancel.model_copy(update={"status": FlowRunStatus.CANCELLED})
    mock_container.flow_run_service.return_value.get_run.return_value = run_before_cancel
    mock_container.flow_run_service.return_value.cancel_run.return_value = cancelled_run
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    response = await cancel_flow_run(
        id=cancelled_run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=mock_container,
    )

    assert response.id == cancelled_run.id
    mock_container.flow_run_service.return_value.get_run.assert_awaited_once_with(run_id=cancelled_run.id)
    mock_container.flow_run_service.return_value.cancel_run.assert_awaited_once_with(run_id=cancelled_run.id)
    mock_container.audit_service.return_value.log_async.assert_awaited_once()
    kwargs = mock_container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_CANCELLED
    assert kwargs["entity_id"] == cancelled_run.id


@pytest.mark.asyncio
async def test_get_flow_run_and_evidence(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    mock_container.flow_run_service.return_value.get_run.side_effect = [run, run]
    mock_container.flow_run_service.return_value.get_evidence.return_value = evidence
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    request = SimpleNamespace(state=SimpleNamespace())
    run_response = await get_flow_run(id=run.id, request=request, container=mock_container)
    evidence_response = await get_flow_run_evidence(id=run.id, request=request, container=mock_container)

    assert run_response.id == run.id
    assert evidence_response.run["id"] == str(run.id)
    assert evidence_response.definition_snapshot == {"steps": []}
    assert evidence_response.debug_export.schema_version == "eneo.flow.debug-export.v1"
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_flow_run_rejects_space_scope_mismatch(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_service.return_value.get_flow.return_value = _flow(space_id=uuid4())
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=uuid4()))

    with pytest.raises(HTTPException) as exc:
        await get_flow_run(
            id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=mock_container,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_cancel_flow_run_rejects_space_scope_mismatch(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_service.return_value.get_flow.return_value = _flow(space_id=uuid4())
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=uuid4()))

    with pytest.raises(HTTPException):
        await cancel_flow_run(
            id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=mock_container,
        )

    mock_container.flow_run_service.return_value.cancel_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_flow_run_evidence_rejects_space_scope_mismatch(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_service.return_value.get_flow.return_value = _flow(space_id=uuid4())
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=uuid4()))

    with pytest.raises(HTTPException):
        await get_flow_run_evidence(
            id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=mock_container,
        )

    mock_container.flow_run_service.return_value.get_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_flow_run_uses_run_scoped_dispatch_and_audits(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.side_effect = [run, run]
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.return_value = 1
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    response = await redispatch_flow_run(
        id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=mock_container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 1
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.assert_awaited_once_with(
        flow_id=run.flow_id,
        run_id=run.id,
        limit=1,
        execution_backend=mock_container.flow_execution_backend.return_value,
    )
    kwargs = mock_container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert kwargs["entity_id"] == run.id


@pytest.mark.asyncio
async def test_redispatch_flow_run_returns_zero_when_nothing_redispatched(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.side_effect = [run, run]
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.return_value = 0
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    response = await redispatch_flow_run(
        id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=mock_container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 0
    kwargs = mock_container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert "dispatch_count=0" in kwargs["description"]


@pytest.mark.asyncio
async def test_redispatch_flow_run_propagates_dispatch_failure(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.side_effect = RuntimeError("broker down")
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=None))

    with pytest.raises(RuntimeError, match="broker down"):
        await redispatch_flow_run(
            id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=mock_container,
        )

    mock_container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_flow_run_rejects_space_scope_mismatch(mock_container, monkeypatch):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    )
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_service.return_value.get_flow.return_value = _flow(space_id=uuid4())
    router_module = importlib.import_module("intric.flows.api.flow_run_router")
    monkeypatch.setattr(router_module, "get_scope_filter", lambda _request: ScopeFilter(space_id=uuid4()))

    with pytest.raises(HTTPException):
        await redispatch_flow_run(
            id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=mock_container,
        )

    mock_container.flow_run_service.return_value.redispatch_stale_queued_runs.assert_not_awaited()
