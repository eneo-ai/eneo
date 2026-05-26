from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

import intric.flows.application.flow_dispatch as flow_dispatch_module
from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_models import (
    FlowRunCreateRequest,
    FlowRunStepRerunRequest,
)
from intric.flows.api.flow_router_common import (
    dispatch_flow_run_after_commit,
    dispatch_flow_run_recoverably_after_commit,
)
from intric.flows.api.flow_run_execution_router import (
    cancel_flow_run_alias,
    create_flow_run,
    get_flow_run_alias,
    list_flow_runs_alias,
    redispatch_flow_run_alias,
    rerun_flow_run_step,
)
from intric.flows.api.flow_run_steps_router import (
    get_flow_graph,
    list_flow_run_steps,
)
from intric.flows.enums import FlowRunRerunOperationStatus
from intric.flows.flow import (
    FlowRunStatus,
    FlowVersion,
)
from intric.flows.flow_run_dispatch_request import (
    FlowRunServiceKeyDispatchRequest,
    FlowRunUserDispatchRequest,
)
from intric.flows.flow_run_step_inputs import FlowRunStepInputFiles
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
)
from intric.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_explicit_transaction,
    _enable_space_access,
    _flow,
    _RecordingBackgroundTasks,
    _rerun_result,
    _result_file,
    _run,
    _service_key,
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
    _enable_space_access(container)

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=live_flow.tenant_id)
    flow_service.get_flow.return_value = live_flow
    flow_run_service.get_run.return_value = run
    flow_run_service.list_step_results.return_value = [
        SimpleNamespace(
            model_dump=lambda mode="json": {
                "step_id": None,
                "step_order": 1,
                "status": "completed",
                "num_tokens_input": 5,
                "num_tokens_output": 9,
                "error_message": None,
            }
        )
    ]
    snapshot_step_id = uuid4()
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow_id),
            "steps": [
                {
                    "step_id": str(snapshot_step_id),
                    "step_order": 1,
                    "assistant_id": str(uuid4()),
                    "user_description": "Snapshot step",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    graph = await get_flow_graph(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_id=run.id,
        container=container,
    )

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].id == str(snapshot_step_id)
    assert llm_nodes[0].label == "Snapshot step"
    # enforce_flow_scope now always loads the flow for space membership checks,
    # but the graph should still be built from the version snapshot, not live flow.
    flow_run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )
    flow_run_service.list_step_results.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_get_flow_graph_uses_live_flow_when_run_id_missing():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()
    _enable_space_access(container)

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    flow_service.get_flow.return_value = live_flow

    graph = await get_flow_graph(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_id=None,
        container=container,
    )

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].label == "Step 1"


@pytest.mark.asyncio
async def test_create_flow_run_allows_service_key_principals():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS])

    flow = _flow(uuid4())
    run = _run(flow_id=flow.id, tenant_id=container.user.return_value.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value=FlowRunServiceKeyDispatchRequest(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=run.tenant_id,
            principal_api_key_id=container.user.return_value.active_api_key.id,
        )
    )
    flow_service.get_flow.return_value = flow

    response = await create_flow_run(
        id=flow.id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=FlowRunCreateRequest(input_payload_json={"text": "hello"}),
        background_tasks=BackgroundTasks(),
        container=container,
    )

    assert response.id == run.id
    flow_run_service.create_run.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_schedules_background_dispatch():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    events: list[str] = []

    def _build_dispatch_request(_run):
        events.append("build_dispatch_request")
        return FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )

    flow_run_service.build_dispatch_request = MagicMock(
        side_effect=_build_dispatch_request
    )
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)

    background_tasks = _RecordingBackgroundTasks(events)
    run_in = FlowRunCreateRequest(input_payload_json={"case_id": "123"})

    response = await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=run_in,
        background_tasks=background_tasks,
        container=container,
    )

    assert response.id == run.id
    assert events == [
        "transaction_enter",
        "build_dispatch_request",
        "transaction_exit",
        "add_task",
    ]
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_after_commit
    assert scheduled.kwargs == {
        "request": FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )
    }
    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        expected_flow_version=None,
        step_inputs=None,
        idempotency_key=None,
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_forwards_idempotency_key():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value=FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )
    )
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

    await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_in=FlowRunCreateRequest(input_payload_json={"case_id": "123"}),
        background_tasks=BackgroundTasks(),
        idempotency_key="idem-123",
        container=container,
    )

    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        expected_flow_version=None,
        step_inputs=None,
        idempotency_key="idem-123",
    )


@pytest.mark.asyncio
async def test_create_flow_run_handles_missing_headers_object():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value=FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )
    )
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

    await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_in=FlowRunCreateRequest(input_payload_json={"case_id": "123"}),
        background_tasks=BackgroundTasks(),
        container=container,
    )

    assert flow_run_service.create_run.await_args.kwargs["idempotency_key"] is None


@pytest.mark.asyncio
async def test_rerun_flow_run_step_calls_service_and_schedules_recoverable_dispatch(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    input_file_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"revision": 2, "status": FlowRunStatus.QUEUED}
    )
    rerun_result = _rerun_result(run, step_id, invalidated_step_ids=(step_id, uuid4()))
    events: list[str] = []
    run_service = AsyncMock()
    rerun_service = AsyncMock()
    rerun_service.rerun_step.return_value = rerun_result

    def _build_dispatch_request(_run):
        events.append("build_dispatch_request")
        return FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )

    run_service.build_dispatch_request = MagicMock(side_effect=_build_dispatch_request)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    _enable_explicit_transaction(container, events)
    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = _RecordingBackgroundTasks(events)
    response = await rerun_flow_run_step(
        id=flow_id,
        run_id=run.id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        rerun_in=FlowRunStepRerunRequest(
            expected_run_revision=1,
            reason="Reviewer accepted corrected transcription",
            input_payload_json={"reviewer_note": "corrected"},
            step_inputs={step_id: {"file_ids": [input_file_id]}},
        ),
        background_tasks=background_tasks,
        container=container,
    )

    assert response.operation_id == rerun_result.operation.id
    assert events == [
        "transaction_enter",
        "build_dispatch_request",
        "transaction_exit",
        "add_task",
    ]
    assert response.run.id == run.id
    assert response.run.revision == 2
    assert response.rerun_step_id == step_id
    assert response.new_attempt_no == 2
    assert response.invalidated_step_ids == [
        step.step_id for step in rerun_result.invalidated_steps
    ]
    assert response.status == FlowRunRerunOperationStatus.QUEUED
    rerun_service.rerun_step.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
        rerun_step_id=step_id,
        expected_run_revision=1,
        reason="Reviewer accepted corrected transcription",
        input_payload_json={"reviewer_note": "corrected"},
        step_inputs={step_id: FlowRunStepInputFiles(file_ids=(input_file_id,))},
    )
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_recoverably_after_commit
    assert scheduled.kwargs == {
        "request": FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )
    }
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_flow_run_step_replay_does_not_schedule_dispatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    rerun_result = _rerun_result(
        run,
        step_id,
        created=False,
        status=FlowRunRerunOperationStatus.COMPLETED,
    )
    run_service = AsyncMock()
    rerun_service = AsyncMock()
    rerun_service.rerun_step.return_value = rerun_result
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = BackgroundTasks()
    response = await rerun_flow_run_step(
        id=flow_id,
        run_id=run.id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        rerun_in=FlowRunStepRerunRequest(
            expected_run_revision=1,
            reason="Replay existing request",
        ),
        background_tasks=background_tasks,
        container=container,
    )

    assert response.status == FlowRunRerunOperationStatus.COMPLETED
    assert background_tasks.tasks == []
    run_service.build_dispatch_request.assert_not_called()
    rerun_service.rerun_step.assert_awaited_once()
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_flow_run_step_stale_revision_does_not_schedule_dispatch(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run_service = AsyncMock()
    rerun_service = AsyncMock()
    rerun_service.rerun_step.side_effect = BadRequestException(
        "Flow run revision is stale.",
        code="flow_run_rerun_stale_revision",
    )
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await rerun_flow_run_step(
            id=flow_id,
            run_id=run_id,
            step_id=step_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            rerun_in=FlowRunStepRerunRequest(
                expected_run_revision=1,
                reason="Stale request",
            ),
            background_tasks=background_tasks,
            container=container,
        )

    assert exc_info.value.code == "flow_run_rerun_stale_revision"
    assert background_tasks.tasks == []
    run_service.build_dispatch_request.assert_not_called()
    rerun_service.rerun_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_marks_failed_on_dispatch_error(
    monkeypatch,
):
    run_repo = AsyncMock()
    terminalizer = AsyncMock()
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

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    request = FlowRunUserDispatchRequest(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_user_id=uuid4(),
    )

    await dispatch_flow_run_after_commit(request=request)

    terminalizer.terminalize_run.assert_awaited_once()
    kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert kwargs["run_id"] == run_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["target_status"] == FlowRunStatus.FAILED
    assert kwargs["error"].code == "flow_dispatch_failed"
    assert kwargs["error"].message == (
        "flow_dispatch_failed: Flow dispatch failed before execution started. "
        "Retry creating a new run."
    )


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_dispatches_without_status_update_on_success(
    monkeypatch,
):
    run_repo = AsyncMock()
    terminalizer = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    fake_session = MagicMock()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_repo(self):
            return run_repo

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    request = FlowRunUserDispatchRequest(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_user_id=user_id,
    )

    await dispatch_flow_run_after_commit(request=request)

    backend.dispatch.assert_awaited_once_with(request=request)
    run_repo.update_status.assert_not_awaited()
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_flow_run_recoverably_after_commit_dispatches_without_terminalization(
    monkeypatch,
):
    run_repo = AsyncMock()
    terminalizer = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    fake_session = MagicMock()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_repo(self):
            return run_repo

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    request = FlowRunUserDispatchRequest(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_user_id=user_id,
    )

    await dispatch_flow_run_recoverably_after_commit(request=request)

    backend.dispatch.assert_awaited_once_with(request=request)
    run_repo.update_status.assert_not_awaited()
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_flow_run_recoverably_after_commit_logs_without_terminalization(
    monkeypatch,
    caplog,
):
    terminalizer = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock(side_effect=RuntimeError("broker down"))
    fake_session = MagicMock()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    caplog.set_level("ERROR", logger=flow_dispatch_module.logger.name)
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    request = FlowRunUserDispatchRequest(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_user_id=uuid4(),
    )

    await dispatch_flow_run_recoverably_after_commit(request=request)

    assert "flow_recoverable_dispatch_after_commit_failed" in caplog.text
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_after_commit_wrappers_dispatch_same_request_shape(monkeypatch):
    terminalizer = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
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

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    request = FlowRunUserDispatchRequest(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        principal_user_id=uuid4(),
    )

    await dispatch_flow_run_after_commit(request=request)
    await dispatch_flow_run_recoverably_after_commit(request=request)

    assert backend.dispatch.await_count == 2
    first_call, second_call = backend.dispatch.await_args_list
    assert first_call.kwargs == second_call.kwargs == {"request": request}
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_endpoints_delegate_to_run_service(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    result_file = _result_file(run=run)
    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    run_service.get_run.return_value = run
    run_service.list_result_files_for_runs.return_value = [result_file]
    run_service.list_token_usage_for_runs.return_value = {}
    run_service.list_step_results_with_files.return_value = SimpleNamespace(
        step_results=[],
        result_files=[],
    )
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    request = SimpleNamespace(state=SimpleNamespace())

    list_response = await list_flow_runs_alias(
        id=flow_id,
        request=request,
        limit=20,
        offset=2,
        container=container,
    )
    get_response = await get_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=request,
        container=container,
    )
    step_response = await list_flow_run_steps(
        id=flow_id,
        run_id=run.id,
        request=request,
        container=container,
    )

    assert list_response["count"] == 1
    assert list_response["has_more"] is False
    assert list_response["items"][0].result_files == [result_file]
    assert get_response.id == run.id
    assert get_response.result_files == [result_file]
    assert step_response == []
    # get_flow is called once per endpoint (3 total) via enforce_flow_scope space check
    assert flow_service.get_flow.await_count == 3
    run_service.list_runs.assert_awaited_once_with(flow_id=flow_id, limit=21, offset=2)
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    assert run_service.list_result_files_for_runs.await_count == 2
    run_service.list_step_results_with_files.assert_awaited_once_with(
        run_id=run.id, flow_id=flow_id
    )


@pytest.mark.asyncio
async def test_flow_run_alias_list_raises_not_found_when_flow_missing_without_scope_filter(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.side_effect = NotFoundException("Flow not found.")
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    with pytest.raises(NotFoundException):
        await list_flow_runs_alias(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=20,
            offset=0,
            container=container,
        )

    run_service.list_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_cancel_uses_terminalizer_audit_only(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    cancelled_run = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    events: list[str] = []

    async def _get_run(**_kwargs):
        events.append("get_run")
        return run

    async def _cancel_run(**_kwargs):
        events.append("cancel_run")
        return cancelled_run

    run_service = AsyncMock()
    run_service.get_run.side_effect = _get_run
    run_service.cancel_run.side_effect = _cancel_run
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)

    response = await cancel_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.id == cancelled_run.id
    assert events == [
        "transaction_enter",
        "get_run",
        "cancel_run",
        "transaction_exit",
    ]
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.cancel_run.assert_awaited_once_with(run_id=run.id)
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_uses_run_scoped_dispatch_and_audits(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    run_service = AsyncMock()
    run_service.get_run.side_effect = [run, run]
    run_service.redispatch_stale_queued_runs.return_value = 1
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    backend = MagicMock()
    container.flow_execution_backend.return_value = backend

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await redispatch_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 1
    run_service.redispatch_stale_queued_runs.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
        limit=1,
        execution_backend=backend,
    )
    kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert kwargs["entity_id"] == run.id


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_returns_zero_when_nothing_redispatched(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    run_service = AsyncMock()
    run_service.get_run.side_effect = [run, run]
    run_service.redispatch_stale_queued_runs.return_value = 0
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    container.flow_execution_backend.return_value = MagicMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await redispatch_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 0
    kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert "dispatch_count=0" in kwargs["description"]


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_propagates_dispatch_failure(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.redispatch_stale_queued_runs.side_effect = RuntimeError("broker down")
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.flow_execution_backend.return_value = MagicMock()
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    with pytest.raises(RuntimeError, match="broker down"):
        await redispatch_flow_run_alias(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    container.audit_service.return_value.log_async.assert_not_awaited()
