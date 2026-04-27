from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.runtime.celery_execution_backend import (
    FLOW_EXECUTE_TASK_NAME,
    CeleryFlowExecutionBackend,
)


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatches_task():
    celery_app = MagicMock()
    backend = CeleryFlowExecutionBackend(
        celery_app=celery_app, queue_name="flows.execute"
    )
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()

    await backend.dispatch(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    celery_app.send_task.assert_called_once_with(
        FLOW_EXECUTE_TASK_NAME,
        kwargs={
            "run_id": str(run_id),
            "flow_id": str(flow_id),
            "tenant_id": str(tenant_id),
            "principal_type": "user",
            "principal_user_id": str(user_id),
            "principal_api_key_id": None,
        },
        queue="flows.execute",
    )


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatches_service_key_principal():
    celery_app = MagicMock()
    backend = CeleryFlowExecutionBackend(
        celery_app=celery_app, queue_name="flows.execute"
    )
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    api_key_id = uuid4()

    await backend.dispatch(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_type="service_key",
        principal_user_id=None,
        principal_api_key_id=api_key_id,
    )

    celery_app.send_task.assert_called_once_with(
        FLOW_EXECUTE_TASK_NAME,
        kwargs={
            "run_id": str(run_id),
            "flow_id": str(flow_id),
            "tenant_id": str(tenant_id),
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": str(api_key_id),
        },
        queue="flows.execute",
    )


@pytest.mark.asyncio
async def test_celery_execution_backend_uses_default_queue_and_none_user(monkeypatch):
    execution_module = importlib.import_module(
        "intric.flows.runtime.celery_execution_backend"
    )
    monkeypatch.setattr(
        execution_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_queue="flows.default"),
    )
    celery_app = MagicMock()
    backend = execution_module.CeleryFlowExecutionBackend(celery_app=celery_app)

    await backend.dispatch(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        user_id=None,
    )

    kwargs = celery_app.send_task.call_args.kwargs
    assert kwargs["queue"] == "flows.default"
    assert kwargs["kwargs"]["principal_type"] == "user"
    assert kwargs["kwargs"]["principal_user_id"] is None


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatch_propagates_send_task_failure():
    celery_app = MagicMock()
    celery_app.send_task.side_effect = RuntimeError("broker unavailable")
    backend = CeleryFlowExecutionBackend(
        celery_app=celery_app, queue_name="flows.execute"
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await backend.dispatch(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
        )


def test_create_flow_celery_app_applies_redis_and_queue_settings(monkeypatch):
    celery_app_module = importlib.import_module("intric.flows.runtime.celery_app")
    shared_celery_app_module = importlib.import_module("intric.worker.celery.app")
    settings = SimpleNamespace(
        redis_host="redis",
        redis_port=6379,
        redis_db_celery_broker=2,
        redis_db_celery_result=3,
        flow_celery_queue="flows.execute",
        celery_visibility_timeout_seconds=7200,
        flow_task_timeout_seconds=540,
    )
    monkeypatch.setattr(celery_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(shared_celery_app_module, "get_settings", lambda: settings)

    app = celery_app_module.create_flow_celery_app()

    assert app.conf.broker_url == "redis://redis:6379/2"
    assert app.conf.result_backend == "redis://redis:6379/3"
    assert app.conf.task_default_queue == "flows.execute"
    assert app.conf.task_routes["flows.execute"]["queue"] == "flows.execute"
    assert app.conf.task_routes["flows.reconcile_running"]["queue"] == "flows.execute"
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late is True
    assert app.conf.task_soft_time_limit == 540
    assert app.conf.task_time_limit == 600
    assert "reconcile-stale-running" in app.conf.beat_schedule


def test_execute_flow_run_marks_failed_when_user_id_is_missing(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    mark_run_failed = AsyncMock()
    monkeypatch.setattr(tasks_module, "_mark_run_failed", mark_run_failed)
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())

    class _Future:
        def result(self, timeout=None):
            return None

    def _run_coroutine_threadsafe(coroutine, _loop):
        asyncio.run(coroutine)
        return _Future()

    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )
    result = tasks_module._execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        user_id=None,
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "missing_principal"}
    assert mark_run_failed.await_count == 1
    assert mark_run_failed.await_args.kwargs["error_message"] == (
        "flow_missing_principal: Flow run execution skipped because run has no execution principal."
    )


def test_execute_flow_run_handles_timeout_and_marks_run_failed(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    mark_run_failed = AsyncMock()
    monkeypatch.setattr(tasks_module, "_mark_run_failed", mark_run_failed)
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: type(
            "_Settings",
            (),
            {"flow_task_timeout_seconds": 1, "flow_max_inline_text_bytes": 1024},
        )(),
    )

    class _RunFuture:
        def cancel(self):
            return None

        def result(self, timeout=None):
            raise concurrent.futures.TimeoutError()

    class _DoneFuture:
        def result(self, timeout=None):
            return None

    calls = {"count": 0}

    def _run_coroutine_threadsafe(coroutine, _loop):
        if calls["count"] == 0:
            calls["count"] += 1
            coroutine.close()
            return _RunFuture()
        asyncio.run(coroutine)
        return _DoneFuture()

    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )
    result = tasks_module._execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "timeout"}
    assert mark_run_failed.await_count == 1
    assert mark_run_failed.await_args.kwargs["error_message"] == (
        "flow_task_timeout: Flow execution timed out before task completion."
    )


def test_execute_flow_run_handles_generic_exception(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    mark_run_failed = AsyncMock()
    monkeypatch.setattr(tasks_module, "_mark_run_failed", mark_run_failed)
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: type("_Settings", (), {"flow_task_timeout_seconds": 10})(),
    )

    class _FailFuture:
        def result(self, timeout=None):
            raise RuntimeError("boom")

    class _DoneFuture:
        def result(self, timeout=None):
            return None

    calls = {"count": 0}

    def _run_coroutine_threadsafe(coroutine, _loop):
        if calls["count"] == 0:
            calls["count"] += 1
            coroutine.close()
            return _FailFuture()
        asyncio.run(coroutine)
        return _DoneFuture()

    monkeypatch.setattr(
        tasks_module.asyncio, "run_coroutine_threadsafe", _run_coroutine_threadsafe
    )

    result = tasks_module._execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "task_failure"}
    assert mark_run_failed.await_count == 1
    assert mark_run_failed.await_args.kwargs["error_message"] == (
        "flow_task_failure: Flow execution task failed before run completion."
    )
    assert "boom" not in mark_run_failed.await_args.kwargs["error_message"]


def test_reconcile_stale_running_task_processes_all_tenants(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    tenant_one = SimpleNamespace(id=uuid4())
    tenant_two = SimpleNamespace(id=uuid4())
    repo = MagicMock()
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant_one, tenant_two])
    repo.list_stale_running_runs = AsyncMock(
        side_effect=[
            [SimpleNamespace(id=uuid4(), tenant_id=tenant_one.id)],
            [SimpleNamespace(id=uuid4(), tenant_id=tenant_two.id)],
        ]
    )
    repo.fail_stale_running_run = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    repo.mark_pending_steps_cancelled = AsyncMock()

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

    class _SessionContext:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: SimpleNamespace(flow_task_timeout_seconds=540),
    )

    result = asyncio.run(tasks_module._reconcile_stale_running_runs_all_tenants())

    assert result["status"] == "ok"
    assert result["reconciled"] == 2
    assert repo.fail_stale_running_run.await_count == 2


def test_flow_worker_process_init_initializes_db_and_http_client(monkeypatch):
    celery_app_module = importlib.import_module("intric.flows.runtime.celery_app")
    init_mock = MagicMock()
    start_mock = MagicMock()
    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://db"),
    )
    monkeypatch.setattr(celery_app_module.sessionmanager, "init", init_mock)
    monkeypatch.setattr(celery_app_module.aiohttp_client, "start", start_mock)
    monkeypatch.setattr(celery_app_module.aiohttp_client, "session", None)

    celery_app_module._on_flow_worker_process_init()

    init_mock.assert_called_once_with("postgresql+asyncpg://db")
    start_mock.assert_called_once_with()


def test_flow_worker_process_shutdown_closes_resources(monkeypatch):
    celery_app_module = importlib.import_module("intric.flows.runtime.celery_app")
    close_mock = MagicMock()
    monkeypatch.setattr(celery_app_module, "_close_flow_worker_resources", close_mock)

    celery_app_module._on_flow_worker_process_shutdown()

    close_mock.assert_called_once_with()


def test_enable_autobegin_for_flow_task_session():
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    sync_session = SimpleNamespace(autobegin=False)
    async_session = SimpleNamespace(sync_session=sync_session)

    tasks_module._enable_autobegin_for_flow_task_session(async_session)

    assert sync_session.autobegin is True
