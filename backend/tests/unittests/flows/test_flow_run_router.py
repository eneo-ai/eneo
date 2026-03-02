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
)


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
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
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
async def test_cancel_flow_run_logs_audit_entry(mock_container):
    run = _run(
        flow_id=uuid4(),
        tenant_id=mock_container.user.return_value.tenant_id,
        user_id=mock_container.user.return_value.id,
    ).model_copy(update={"status": FlowRunStatus.CANCELLED})
    mock_container.flow_run_service.return_value.cancel_run.return_value = run

    response = await cancel_flow_run(id=run.id, container=mock_container)

    assert response.id == run.id
    mock_container.audit_service.return_value.log_async.assert_awaited_once()
    kwargs = mock_container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_CANCELLED
    assert kwargs["entity_id"] == run.id


@pytest.mark.asyncio
async def test_get_flow_run_and_evidence(mock_container):
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
    }
    mock_container.flow_run_service.return_value.get_run.return_value = run
    mock_container.flow_run_service.return_value.get_evidence.return_value = evidence

    run_response = await get_flow_run(id=run.id, container=mock_container)
    evidence_response = await get_flow_run_evidence(id=run.id, container=mock_container)

    assert run_response.id == run.id
    assert evidence_response.run["id"] == str(run.id)
    assert evidence_response.definition_snapshot == {"steps": []}
