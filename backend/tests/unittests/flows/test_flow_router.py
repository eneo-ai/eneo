from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.flow import Flow, FlowRun, FlowRunStatus, FlowStep, FlowVersion
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowRunCreateRequest,
    FlowStepCreateRequest,
)
from intric.flows.api.flow_router import (
    create_flow,
    create_flow_assistant,
    create_flow_run,
    get_flow_graph,
    update_flow_assistant,
)
from intric.assistants.api.assistant_models import AssistantUpdatePublic


def _flow_step(step_id, step_order: int) -> FlowStep:
    return FlowStep(
        id=step_id,
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
        mcp_policy="inherit",
    )


def _flow(flow_id):
    now = datetime.now(timezone.utc)
    return Flow(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=uuid4(),
        owner_user_id=uuid4(),
        published_version=1,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=[_flow_step(uuid4(), 1)],
    )


def _run(flow_id, tenant_id):
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        user_id=uuid4(),
        tenant_id=tenant_id,
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_get_flow_graph_uses_run_version_snapshot_when_run_id_supplied():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    flow_version_repo = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.flow_version_repo.return_value = flow_version_repo

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=live_flow.tenant_id)
    flow_service.get_flow.return_value = live_flow
    flow_run_service.get_run.return_value = run
    flow_run_service.get_evidence.return_value = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [
            {
                "step_id": None,
                "step_order": 1,
                "status": "completed",
                "num_tokens_input": 5,
                "num_tokens_output": 9,
                "error_message": None,
            }
        ],
        "step_attempts": [],
    }
    snapshot_step_id = uuid4()
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(snapshot_step_id),
                    "step_order": 1,
                    "user_description": "Snapshot step",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    graph = await get_flow_graph(id=flow_id, run_id=run.id, container=container)

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["id"] == str(snapshot_step_id)
    assert llm_nodes[0]["label"] == "Snapshot step"
    flow_service.get_flow.assert_not_called()


@pytest.mark.asyncio
async def test_get_flow_graph_uses_live_flow_when_run_id_missing():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    flow_service.get_flow.return_value = live_flow

    graph = await get_flow_graph(id=flow_id, run_id=None, container=container)

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["label"] == "Step 1"


@pytest.mark.asyncio
async def test_create_flow_run_schedules_background_dispatch():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    background_tasks = BackgroundTasks()
    run_in = FlowRunCreateRequest(input_payload_json={"case_id": "123"})

    response = await create_flow_run(
        id=flow_id,
        run_in=run_in,
        background_tasks=background_tasks,
        container=container,
    )

    assert response.id == run.id
    assert len(background_tasks.tasks) == 1
    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        file_ids=None,
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_marks_failed_on_dispatch_error(monkeypatch):
    router_module = __import__("intric.flows.api.flow_router", fromlist=["_dispatch_flow_run_after_commit"])

    run_repo = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock(side_effect=RuntimeError("broker down"))

    fake_session = MagicMock()

    class _BeginContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_session.begin = lambda: _BeginContext()

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_repo(self):
            return run_repo

    monkeypatch.setattr(router_module.sessionmanager, "session", lambda: _SessionContext())
    monkeypatch.setattr(router_module, "Container", lambda session: _FakeContainer())

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()

    await router_module._dispatch_flow_run_after_commit(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=uuid4(),
    )

    run_repo.update_status.assert_awaited_once()
    kwargs = run_repo.update_status.await_args.kwargs
    assert kwargs["run_id"] == run_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["status"] == FlowRunStatus.FAILED
    assert kwargs["error_message"].startswith("Flow dispatch failed:")


@pytest.mark.asyncio
async def test_create_flow_rejects_space_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = AsyncMock()

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    allowed_space_id = uuid4()
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=allowed_space_id),
    )

    with pytest.raises(HTTPException) as exc:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=FlowCreateRequest(
                space_id=uuid4(),
                name="Flow",
                steps=[
                    FlowStepCreateRequest(
                        assistant_id=uuid4(),
                        step_order=1,
                        user_description="Step",
                        input_source="flow_input",
                        input_type="text",
                        output_mode="pass_through",
                        output_type="json",
                        mcp_policy="inherit",
                    )
                ],
            ),
            container=container,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_create_flow_assistant_calls_flow_scoped_service():
    container = MagicMock()
    flow_service = AsyncMock()
    assistant_assembler = MagicMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    assistant = SimpleNamespace(
        id=uuid4(),
        name="Step assistant",
        space_id=uuid4(),
        type=SimpleNamespace(value="assistant"),
        completion_model_kwargs=None,
        data_retention_days=None,
        published=False,
    )
    flow_service.create_flow_assistant.return_value = (assistant, [])
    assistant_assembler.from_assistant_to_model.return_value = {"id": str(assistant.id)}
    container.flow_service.return_value = flow_service
    container.assistant_assembler.return_value = assistant_assembler
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    response = await create_flow_assistant(
        id=flow_id,
        assistant_in=FlowAssistantCreateRequest(name="Step assistant"),
        container=container,
    )

    assert response["id"] == str(assistant.id)
    flow_service.create_flow_assistant.assert_awaited_once_with(
        flow_id=flow_id,
        name="Step assistant",
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flow_assistant_forwards_payload():
    container = MagicMock()
    flow_service = AsyncMock()
    assistant_assembler = MagicMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    assistant_id = uuid4()
    updated_assistant = SimpleNamespace(
        id=assistant_id,
        name="Updated assistant",
        space_id=uuid4(),
        type=SimpleNamespace(value="assistant"),
        completion_model_kwargs=None,
        data_retention_days=None,
        published=False,
    )
    flow_service.update_flow_assistant.return_value = (updated_assistant, [])
    assistant_assembler.from_assistant_to_model.return_value = {"id": str(assistant_id)}
    container.flow_service.return_value = flow_service
    container.assistant_assembler.return_value = assistant_assembler
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    response = await update_flow_assistant(
        id=flow_id,
        assistant_id=assistant_id,
        assistant_in=AssistantUpdatePublic(name="Updated assistant"),
        container=container,
    )

    assert response["id"] == str(assistant_id)
    flow_service.update_flow_assistant.assert_awaited_once()
    kwargs = flow_service.update_flow_assistant.await_args.kwargs
    assert kwargs["flow_id"] == flow_id
    assert kwargs["assistant_id"] == assistant_id
    assert kwargs["name"] == "Updated assistant"
    audit_service.log_async.assert_awaited_once()
