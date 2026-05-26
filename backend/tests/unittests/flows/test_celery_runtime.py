from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_run_dispatch_request import (
    FlowRunServiceKeyDispatchRequest,
    FlowRunUserDispatchRequest,
)
from intric.flows.runtime.celery_execution_backend import (
    FLOW_EXECUTE_TASK_NAME,
    CeleryFlowExecutionBackend,
)


def _fake_flow_task_session():
    """Mock session that supports `enable_autobegin_for_flow_task_session`
    and `async with session.begin():` as no-ops, for unit tests that do
    not exercise real SQLAlchemy semantics."""

    class _BeginContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    return SimpleNamespace(
        sync_session=SimpleNamespace(autobegin=False),
        begin=lambda: _BeginContext(),
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
        request=FlowRunUserDispatchRequest(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            principal_user_id=user_id,
        ),
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
        request=FlowRunServiceKeyDispatchRequest(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            principal_api_key_id=api_key_id,
        ),
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
async def test_celery_execution_backend_uses_default_queue(monkeypatch):
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
        request=FlowRunUserDispatchRequest(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            principal_user_id=uuid4(),
        ),
    )

    kwargs = celery_app.send_task.call_args.kwargs
    assert kwargs["queue"] == "flows.default"
    assert kwargs["kwargs"]["principal_type"] == "user"
    assert kwargs["kwargs"]["principal_user_id"] is not None


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatch_propagates_send_task_failure():
    celery_app = MagicMock()
    celery_app.send_task.side_effect = RuntimeError("broker unavailable")
    backend = CeleryFlowExecutionBackend(
        celery_app=celery_app, queue_name="flows.execute"
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await backend.dispatch(
            request=FlowRunUserDispatchRequest(
                run_id=uuid4(),
                flow_id=uuid4(),
                tenant_id=uuid4(),
                principal_user_id=uuid4(),
            ),
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
    assert (
        app.conf.task_routes["flows.deliver_audit_outbox"]["queue"] == "flows.execute"
    )
    assert (
        app.conf.task_routes["flows.deliver_webhook_outbox"]["queue"] == "flows.execute"
    )
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late is True
    assert app.conf.task_soft_time_limit == 540
    assert app.conf.task_time_limit == 600
    assert "reconcile-stale-running" in app.conf.beat_schedule
    assert "deliver-flow-audit-outbox" in app.conf.beat_schedule
    assert "deliver-flow-webhook-outbox" in app.conf.beat_schedule
    assert (
        app.conf.beat_schedule["deliver-flow-audit-outbox"]["task"]
        == "flows.deliver_audit_outbox"
    )
    assert (
        app.conf.beat_schedule["deliver-flow-webhook-outbox"]["task"]
        == "flows.deliver_webhook_outbox"
    )


def test_execute_flow_run_marks_failed_when_user_id_is_missing(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
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
    assert terminalize_failure.await_count == 1
    assert terminalize_failure.await_args.kwargs["source"] == (
        FlowRunLifecycleSource.MISSING_PRINCIPAL
    )
    error = terminalize_failure.await_args.kwargs["error"]
    assert error.code == ("flow_missing_principal")
    assert error.message == (
        "flow_missing_principal: Flow run execution skipped because run has no execution principal."
    )


def test_execute_flow_run_handles_timeout_and_marks_run_failed(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
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
    assert terminalize_failure.await_count == 1
    assert terminalize_failure.await_args.kwargs["source"] == (
        FlowRunLifecycleSource.TASK_TIMEOUT
    )
    error = terminalize_failure.await_args.kwargs["error"]
    assert error.code == "flow_task_timeout"
    assert error.message == (
        "flow_task_timeout: Flow execution timed out before task completion."
    )


def test_execute_flow_run_handles_generic_exception(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
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
    assert terminalize_failure.await_count == 1
    assert terminalize_failure.await_args.kwargs["source"] == (
        FlowRunLifecycleSource.TASK_FAILURE
    )
    error = terminalize_failure.await_args.kwargs["error"]
    assert error.code == "flow_task_failure"
    assert error.message == (
        "flow_task_failure: Flow execution task failed before run completion."
    )
    assert "boom" not in error.message


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
    terminalizer = MagicMock()
    terminalizer.terminalize_stale_running_run = AsyncMock(
        return_value=SimpleNamespace(did_transition=True)
    )

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def flow_run_terminalizer(self):
            return terminalizer

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
    assert terminalizer.terminalize_stale_running_run.await_count == 2
    assert {
        call.kwargs["error"].code
        for call in terminalizer.terminalize_stale_running_run.await_args_list
    } == {"flow_worker_stalled"}


def test_reconcile_review_expiry_task_processes_all_tenants(monkeypatch):
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    tenant_one = SimpleNamespace(id=uuid4())
    tenant_two = SimpleNamespace(id=uuid4())
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant_one, tenant_two])
    reconciler = MagicMock()
    reconciler.reconcile_next_expired_checkpoint = AsyncMock(
        side_effect=[1, 1, 0, 1, 0]
    )

    class _Container:
        def __init__(self, session=None):
            self._tenant_repo = tenant_repo

        def tenant_repo(self):
            return self._tenant_repo

        def flow_review_expiry_reconciler(self):
            return reconciler

    class _SessionContext:
        async def __aenter__(self):
            return _fake_flow_task_session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(
        tasks_module._reconcile_expired_review_checkpoints_all_tenants()
    )

    assert result == {"status": "ok", "reconciled": 3}
    assert reconciler.reconcile_next_expired_checkpoint.await_count == 5
    assert {
        call.kwargs["tenant_id"]
        for call in reconciler.reconcile_next_expired_checkpoint.await_args_list
    } == {tenant_one.id, tenant_two.id}


def test_redispatch_stale_queued_task_processes_all_tenants(monkeypatch):
    """Beat-driven redispatch claims stuck QUEUED runs and dispatches them.

    Without this safety net, a run whose post-response BackgroundTask
    dispatch silently fails (FastAPI process restart, OOM, autoreload)
    sits in QUEUED forever with no error_code and no retry. The beat
    task is the only automatic recovery — `cancel_run` only flips DB
    status, and `reconcile-stale-running` handles RUNNING, not QUEUED.
    """
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    tenant_one = SimpleNamespace(id=uuid4())
    tenant_two = SimpleNamespace(id=uuid4())
    user_run_user_id = uuid4()
    service_key_id = uuid4()
    user_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant_one.id,
        principal_type="user",
        principal_user_id=user_run_user_id,
        principal_api_key_id=None,
    )
    service_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant_two.id,
        principal_type="service_key",
        principal_user_id=None,
        principal_api_key_id=service_key_id,
    )
    repo = MagicMock()
    repo.list_stale_queued_runs = AsyncMock(side_effect=[[user_run], [service_run]])
    repo.claim_stale_queued_run_for_redispatch = AsyncMock(
        side_effect=[user_run, service_run]
    )
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant_one, tenant_two])
    backend = MagicMock()
    backend.dispatch = AsyncMock()

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo
            self._backend = backend

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

        def flow_execution_backend(self):
            return self._backend

    fake_session = _fake_flow_task_session()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result["status"] == "ok"
    assert result["redispatched"] == 2
    assert backend.dispatch.await_count == 2
    user_request = backend.dispatch.await_args_list[0].kwargs["request"]
    assert user_request == FlowRunUserDispatchRequest(
        run_id=user_run.id,
        flow_id=user_run.flow_id,
        tenant_id=tenant_one.id,
        principal_user_id=user_run_user_id,
    )
    service_request = backend.dispatch.await_args_list[1].kwargs["request"]
    assert service_request == FlowRunServiceKeyDispatchRequest(
        run_id=service_run.id,
        flow_id=service_run.flow_id,
        tenant_id=tenant_two.id,
        principal_api_key_id=service_key_id,
    )


def test_redispatch_stale_queued_skips_runs_lost_to_concurrent_claim(monkeypatch):
    """If `claim_stale_queued_run_for_redispatch` returns None, skip dispatch.

    A concurrent dispatch path or a recently-RUNNING-transitioned run
    must not be redispatched twice; the atomic claim is the
    cross-process serialization point.
    """
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    stale_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        principal_type="user",
        principal_user_id=uuid4(),
        principal_api_key_id=None,
    )
    repo = MagicMock()
    repo.list_stale_queued_runs = AsyncMock(return_value=[stale_run])
    repo.claim_stale_queued_run_for_redispatch = AsyncMock(return_value=None)
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant])
    backend = MagicMock()
    backend.dispatch = AsyncMock()

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo
            self._backend = backend

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

        def flow_execution_backend(self):
            return self._backend

    fake_session = _fake_flow_task_session()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result["redispatched"] == 0
    assert backend.dispatch.await_count == 0


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

    tasks_module.enable_autobegin_for_flow_task_session(async_session)

    assert sync_session.autobegin is True


def test_redispatch_stale_queued_commits_claim_before_dispatch(monkeypatch):
    """The atomic UPDATE must commit before the celery dispatch fires.

    With `autobegin=False` on the sessionmaker the beat task must enable
    autobegin for the session and wrap the claim in `session.begin()`.
    Otherwise the claim either raises (no transaction is open) or is
    not yet visible to the worker that picks up the dispatched run.
    """
    tasks_module = importlib.import_module("intric.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    stale_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        principal_type="user",
        principal_user_id=uuid4(),
        principal_api_key_id=None,
    )
    events: list[str] = []
    repo = MagicMock()

    async def list_stale(**_kwargs):
        events.append("list_stale")
        return [stale_run]

    async def claim(**_kwargs):
        events.append("claim")
        return stale_run

    repo.list_stale_queued_runs = list_stale
    repo.claim_stale_queued_run_for_redispatch = claim
    tenant_repo = MagicMock()

    async def get_all_tenants():
        events.append("get_tenants")
        return [tenant]

    tenant_repo.get_all_tenants = get_all_tenants
    backend = MagicMock()

    async def dispatch(**_kwargs):
        events.append("dispatch")

    backend.dispatch = dispatch

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo
            self._backend = backend

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

        def flow_execution_backend(self):
            return self._backend

    class _BeginContext:
        async def __aenter__(self):
            events.append("begin")
            return None

        async def __aexit__(self, exc_type, _exc, _tb):
            events.append("commit" if exc_type is None else "rollback")
            return False

    sync_session = SimpleNamespace(autobegin=False)
    fake_session = SimpleNamespace(
        sync_session=sync_session,
        begin=lambda: _BeginContext(),
    )

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result == {"status": "ok", "redispatched": 1}
    assert sync_session.autobegin is True, (
        "Beat task must enable autobegin so the claim UPDATE opens a "
        "transaction; with autobegin=False it raises InvalidRequestError."
    )
    claim_idx = events.index("claim")
    dispatch_idx = events.index("dispatch")
    commits_between = [
        i
        for i, e in enumerate(events)
        if e == "commit" and claim_idx < i < dispatch_idx
    ]
    assert commits_between, (
        f"Expected claim→commit→dispatch ordering; got {events}. "
        "Without a commit between claim and dispatch, the worker may "
        "pick up the run before the QUEUED-claim is visible."
    )
