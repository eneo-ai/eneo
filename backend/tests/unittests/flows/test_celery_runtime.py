from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import threading
from collections import deque
from collections.abc import Coroutine
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchAccepted,
    FlowRunDispatchFailed,
    FlowRunDispatchNotClaimed,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_run_dispatch_request import (
    FlowRunDispatchMalformedPayload,
    FlowRunDispatchMalformedReason,
    FlowRunServiceKeyDispatchRequest,
    FlowRunUserDispatchRequest,
    flow_run_dispatch_task_kwargs,
    parse_flow_run_dispatch_task_kwargs,
)
from eneo.flows.runtime.celery_execution_backend import (
    FLOW_EXECUTE_TASK_NAME,
    CeleryFlowExecutionBackend,
)

EXPECTED_FLOW_CELERY_TASKS = {
    "flows.execute",
    "flows.reconcile_running",
    "flows.reconcile_review_expiry",
    "flows.redispatch_stale_queued",
    "flows.deliver_audit_outbox",
    "flows.deliver_webhook_outbox",
}


def _fake_flow_task_session(events: list[str] | None = None):
    """Mock session that supports `enable_autobegin_for_flow_task_session`
    and `async with session.begin():` as no-ops, for unit tests that do
    not exercise real SQLAlchemy semantics."""

    class _BeginContext:
        async def __aenter__(self):
            if events is not None:
                events.append("begin")
            return None

        async def __aexit__(self, _exc_type, _exc, _tb):
            if events is not None:
                events.append("commit" if _exc_type is None else "rollback")
            return False

    return SimpleNamespace(
        sync_session=SimpleNamespace(autobegin=False),
        begin=lambda: _BeginContext(),
    )


def test_flow_run_dispatch_parser_round_trips_user_task_kwargs():
    request = FlowRunUserDispatchRequest(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        run_revision=3,
        principal_user_id=uuid4(),
    )
    kwargs = flow_run_dispatch_task_kwargs(request)

    result = parse_flow_run_dispatch_task_kwargs(
        run_id=str(kwargs["run_id"]),
        flow_id=str(kwargs["flow_id"]),
        tenant_id=str(kwargs["tenant_id"]),
        run_revision=kwargs["run_revision"],
        principal_type=kwargs["principal_type"],
        principal_user_id=kwargs["principal_user_id"],
        principal_service_id=kwargs["principal_service_id"],
    )

    assert result == request


def test_flow_run_dispatch_parser_round_trips_service_key_task_kwargs():
    request = FlowRunServiceKeyDispatchRequest(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        run_revision=4,
        principal_service_id=uuid4(),
    )
    kwargs = flow_run_dispatch_task_kwargs(request)

    result = parse_flow_run_dispatch_task_kwargs(
        run_id=str(kwargs["run_id"]),
        flow_id=str(kwargs["flow_id"]),
        tenant_id=str(kwargs["tenant_id"]),
        run_revision=kwargs["run_revision"],
        principal_type=kwargs["principal_type"],
        principal_user_id=kwargs["principal_user_id"],
        principal_service_id=kwargs["principal_service_id"],
    )

    assert result == request


def test_flow_run_dispatch_parser_rejects_missing_user_principal():
    result = parse_flow_run_dispatch_task_kwargs(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="user",
    )

    assert result == FlowRunDispatchMalformedPayload(
        reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_USER_ID
    )


def test_flow_run_dispatch_parser_rejects_missing_service_key_principal():
    result = parse_flow_run_dispatch_task_kwargs(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="service_key",
    )

    assert result == FlowRunDispatchMalformedPayload(
        reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_SERVICE_ID
    )


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        (
            {"run_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_RUN_ID,
        ),
        (
            {"tenant_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_TENANT_ID,
        ),
        (
            {"run_revision": 0},
            FlowRunDispatchMalformedReason.INVALID_RUN_REVISION,
        ),
        (
            {"flow_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_FLOW_ID,
        ),
        (
            {"principal_type": "robot"},
            FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_TYPE,
        ),
        (
            {"principal_user_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_USER_ID,
        ),
        (
            {
                "principal_type": "service_key",
                "principal_service_id": "not-a-uuid",
            },
            FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_SERVICE_ID,
        ),
    ],
)
def test_flow_run_dispatch_parser_reports_malformed_reason(payload, expected_reason):
    base_payload = {
        "run_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "run_revision": 1,
        "principal_type": "user",
        "principal_user_id": str(uuid4()),
        "principal_service_id": None,
    }
    base_payload.update(payload)

    result = parse_flow_run_dispatch_task_kwargs(**base_payload)

    assert result == FlowRunDispatchMalformedPayload(reason=expected_reason)


def test_flow_run_dispatch_parser_reports_first_malformed_field():
    result = parse_flow_run_dispatch_task_kwargs(
        run_id="not-a-run-id",
        flow_id="not-a-flow-id",
        tenant_id="not-a-tenant-id",
        run_revision=0,
        principal_type="robot",
        principal_user_id="not-a-user-id",
        principal_service_id="not-a-service-id",
    )

    assert result == FlowRunDispatchMalformedPayload(
        reason=FlowRunDispatchMalformedReason.INVALID_RUN_ID
    )


def test_flow_run_dispatch_parser_has_no_logger():
    dispatch_module = importlib.import_module("eneo.flows.flow_run_dispatch_request")

    assert not hasattr(dispatch_module, "logger")


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatches_task(monkeypatch):
    execution_module = importlib.import_module(
        "eneo.flows.runtime.celery_execution_backend"
    )
    logger = MagicMock()
    monkeypatch.setattr(execution_module, "logger", logger)
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "celery-task-1"
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
            run_revision=5,
            principal_user_id=user_id,
        ),
    )

    celery_app.send_task.assert_called_once_with(
        FLOW_EXECUTE_TASK_NAME,
        kwargs={
            "run_id": str(run_id),
            "flow_id": str(flow_id),
            "tenant_id": str(tenant_id),
            "run_revision": 5,
            "principal_type": "user",
            "principal_user_id": str(user_id),
            "principal_service_id": None,
        },
        queue="flows.execute",
    )
    logger.info.assert_called_once()
    assert logger.info.call_args.kwargs["extra"]["celery_task_id"] == "celery-task-1"


@pytest.mark.asyncio
async def test_celery_execution_backend_dispatches_service_key_principal(monkeypatch):
    execution_module = importlib.import_module(
        "eneo.flows.runtime.celery_execution_backend"
    )
    logger = MagicMock()
    monkeypatch.setattr(execution_module, "logger", logger)
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "celery-task-2"
    backend = CeleryFlowExecutionBackend(
        celery_app=celery_app, queue_name="flows.execute"
    )
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    service_principal_id = uuid4()

    await backend.dispatch(
        request=FlowRunServiceKeyDispatchRequest(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            run_revision=6,
            principal_service_id=service_principal_id,
        ),
    )

    celery_app.send_task.assert_called_once_with(
        FLOW_EXECUTE_TASK_NAME,
        kwargs={
            "run_id": str(run_id),
            "flow_id": str(flow_id),
            "tenant_id": str(tenant_id),
            "run_revision": 6,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_service_id": str(service_principal_id),
        },
        queue="flows.execute",
    )
    logger.info.assert_called_once()
    assert logger.info.call_args.kwargs["extra"]["celery_task_id"] == "celery-task-2"


@pytest.mark.asyncio
async def test_celery_execution_backend_uses_default_queue(monkeypatch):
    execution_module = importlib.import_module(
        "eneo.flows.runtime.celery_execution_backend"
    )
    monkeypatch.setattr(
        execution_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_queue="flows.default"),
    )
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "celery-task-default"
    backend = execution_module.CeleryFlowExecutionBackend(celery_app=celery_app)

    await backend.dispatch(
        request=FlowRunUserDispatchRequest(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            run_revision=1,
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
                run_revision=1,
                principal_user_id=uuid4(),
            ),
        )


def test_create_flow_celery_app_applies_redis_and_queue_settings(monkeypatch):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    shared_celery_app_module = importlib.import_module("eneo.worker.celery.app")
    settings = SimpleNamespace(
        redis_host="redis",
        redis_port=6379,
        redis_db_celery_broker=2,
        redis_db_celery_result=3,
        flow_celery_queue="flows.execute",
        flow_celery_maintenance_queue="flows.maintenance",
        celery_visibility_timeout_seconds=7200,
        flow_task_timeout_seconds=540,
        redis_conn_timeout=5,
        redis_retry_on_timeout=True,
        redis_socket_keepalive=True,
        redis_health_check_interval=30,
        redis_max_connections=64,
    )
    monkeypatch.setattr(celery_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(shared_celery_app_module, "get_settings", lambda: settings)

    app = celery_app_module.create_flow_celery_app()

    assert app.conf.broker_url == "redis://redis:6379/2"
    assert app.conf.result_backend == "redis://redis:6379/3"
    assert app.conf.task_default_queue == "flows.execute"
    assert app.conf.task_routes["flows.execute"]["queue"] == "flows.execute"
    assert (
        app.conf.task_routes["flows.reconcile_running"]["queue"] == "flows.maintenance"
    )
    assert (
        app.conf.task_routes["flows.reconcile_review_expiry"]["queue"]
        == "flows.maintenance"
    )
    assert (
        app.conf.task_routes["flows.redispatch_stale_queued"]["queue"]
        == "flows.maintenance"
    )
    assert (
        app.conf.task_routes["flows.deliver_audit_outbox"]["queue"]
        == "flows.maintenance"
    )
    assert (
        app.conf.task_routes["flows.deliver_webhook_outbox"]["queue"]
        == "flows.maintenance"
    )
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late is True
    assert app.conf.broker_connection_retry_on_startup is True
    assert app.conf.broker_connection_timeout == 5
    expected_transport_options = {
        "visibility_timeout": 7200,
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": True,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "max_connections": 64,
    }
    assert app.conf.broker_transport_options == expected_transport_options
    assert app.conf.result_backend_transport_options == expected_transport_options
    assert app.conf.visibility_timeout == 7200
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


def test_maintenance_consumer_probe_recognizes_configured_queue(monkeypatch):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    app = MagicMock()
    app.control.inspect.return_value.active_queues.return_value = {
        "celery@flow-worker": [
            {"name": "flows.execute"},
            {"name": "flows.maintenance"},
        ]
    }
    monkeypatch.setattr(celery_app_module, "celery_app", app)
    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_maintenance_queue="flows.maintenance"),
    )

    assert celery_app_module.flow_maintenance_queue_has_live_consumer(
        timeout_seconds=0.25
    )
    app.control.inspect.assert_called_once_with(timeout=0.25)


def test_maintenance_consumer_probe_rejects_execution_queues_only(monkeypatch):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    app = MagicMock()
    app.control.inspect.return_value.active_queues.return_value = {
        "celery@flow-worker": [{"name": "flows.execute"}]
    }
    monkeypatch.setattr(celery_app_module, "celery_app", app)
    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_maintenance_queue="flows.maintenance"),
    )

    assert not celery_app_module.flow_maintenance_queue_has_live_consumer(
        timeout_seconds=0.25
    )


@pytest.mark.parametrize(
    "active_queues",
    [None, [], {"celery@flow-worker": None}, {"celery@flow-worker": ["invalid"]}],
)
def test_maintenance_consumer_probe_rejects_malformed_replies(
    monkeypatch, active_queues
):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    app = MagicMock()
    app.control.inspect.return_value.active_queues.return_value = active_queues
    monkeypatch.setattr(celery_app_module, "celery_app", app)
    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_maintenance_queue="flows.maintenance"),
    )

    assert not celery_app_module.flow_maintenance_queue_has_live_consumer(
        timeout_seconds=0.25
    )


@pytest.mark.parametrize(
    "failure", [TimeoutError(), RuntimeError("broker unavailable")]
)
def test_maintenance_consumer_probe_translates_inspection_failure(monkeypatch, failure):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    app = MagicMock()
    app.control.inspect.return_value.active_queues.side_effect = failure
    monkeypatch.setattr(celery_app_module, "celery_app", app)
    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(flow_celery_maintenance_queue="flows.maintenance"),
    )

    assert not celery_app_module.flow_maintenance_queue_has_live_consumer(
        timeout_seconds=0.25
    )


def test_flow_worker_cli_app_path_loads_registered_flow_tasks():
    cli_module = importlib.import_module("eneo.flows.runtime.cli")
    app_module_name, _, app_attr = cli_module.FLOW_CELERY_APP.partition(":")
    celery_app = getattr(importlib.import_module(app_module_name), app_attr)

    importlib.import_module("eneo.flows.runtime.tasks")

    assert EXPECTED_FLOW_CELERY_TASKS <= set(celery_app.tasks)


def test_flow_worker_cli_runs_preflight_then_installed_package_celery_app(
    monkeypatch: pytest.MonkeyPatch,
):
    cli_module = importlib.import_module("eneo.flows.runtime.cli")
    calls: list[str | tuple[str, str, list[str]]] = []
    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: SimpleNamespace(
            flow_celery_queue="flows.custom",
            flow_celery_worker_queues=None,
        ),
    )
    monkeypatch.setattr(cli_module, "get_loglevel", lambda: 10)
    monkeypatch.setattr(
        cli_module.celery_preflight,
        "run_preflight",
        lambda: calls.append("preflight"),
    )

    def fake_execvp(file: str, args: list[str]) -> None:
        calls.append(("execvp", file, args))
        raise SystemExit(0)

    monkeypatch.setattr(cli_module.os, "execvp", fake_execvp)

    with pytest.raises(SystemExit):
        cli_module.worker()

    assert calls[0] == "preflight"
    assert calls[1] == (
        "execvp",
        "celery",
        [
            "celery",
            "-A",
            "eneo.flows.runtime.celery_app:celery_app",
            "worker",
            "--loglevel",
            "DEBUG",
            "--queues",
            "flows.custom",
        ],
    )


def test_flow_worker_cli_uses_worker_queue_override(monkeypatch: pytest.MonkeyPatch):
    cli_module = importlib.import_module("eneo.flows.runtime.cli")
    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: SimpleNamespace(
            flow_celery_queue="flows.execute",
            flow_celery_worker_queues="flows.maintenance",
        ),
    )
    monkeypatch.setattr(cli_module, "get_loglevel", lambda: 20)

    assert cli_module._flow_worker_argv()[-2:] == [
        "--queues",
        "flows.maintenance",
    ]


def test_flow_beat_cli_uses_installed_package_celery_app_and_schedule_file(
    monkeypatch: pytest.MonkeyPatch,
):
    cli_module = importlib.import_module("eneo.flows.runtime.cli")
    monkeypatch.setattr(cli_module, "get_loglevel", lambda: 30)
    monkeypatch.setenv("CELERYBEAT_SCHEDULE_FILE", "/var/run/flows/celerybeat")
    exec_calls: list[tuple[str, list[str]]] = []

    def fake_execvp(file: str, args: list[str]) -> None:
        exec_calls.append((file, args))
        raise SystemExit(0)

    monkeypatch.setattr(cli_module.os, "execvp", fake_execvp)

    with pytest.raises(SystemExit):
        cli_module.beat()

    assert exec_calls == [
        (
            "celery",
            [
                "celery",
                "-A",
                "eneo.flows.runtime.celery_app:celery_app",
                "beat",
                "--loglevel",
                "WARNING",
                "--pidfile=",
                "--schedule=/var/run/flows/celerybeat",
            ],
        )
    ]


def test_execute_flow_run_rejects_missing_user_id_without_terminalizing(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
    result = tasks_module._execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="user",
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "invalid_dispatch_payload"}
    terminalize_failure.assert_not_awaited()


def test_execute_flow_run_rejects_missing_service_id_without_terminalizing(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
    result = tasks_module._execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="service_key",
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "invalid_dispatch_payload"}
    terminalize_failure.assert_not_awaited()


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        (
            {"run_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_RUN_ID,
        ),
        (
            {"flow_id": "not-a-uuid"},
            FlowRunDispatchMalformedReason.INVALID_FLOW_ID,
        ),
        (
            {"principal_type": "robot"},
            FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_TYPE,
        ),
    ],
)
def test_execute_flow_run_rejects_malformed_dispatch_payload_without_runtime(
    monkeypatch, payload, expected_reason
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    execute_async = AsyncMock()
    logger = MagicMock()
    get_loop = MagicMock(side_effect=AssertionError("malformed payload requested loop"))
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
    monkeypatch.setattr(tasks_module, "_execute_flow_run_async", execute_async)
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", get_loop)
    monkeypatch.setattr(tasks_module, "logger", logger)
    base_payload = {
        "run_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "run_revision": 1,
        "principal_type": "user",
        "principal_user_id": str(uuid4()),
        "principal_service_id": None,
    }
    base_payload.update(payload)

    result = tasks_module._execute_flow_run_task(
        **base_payload,
        task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "invalid_dispatch_payload"}
    terminalize_failure.assert_not_awaited()
    execute_async.assert_not_called()
    get_loop.assert_not_called()
    logger.error.assert_called_once()
    log_extra = logger.error.call_args.kwargs["extra"]
    assert log_extra["parse_reason"] == expected_reason.value
    assert log_extra["task_id"] == "task-1"


@pytest.mark.parametrize("trigger", ["timeout", "soft_time_limit"])
def test_execute_flow_run_waits_for_execution_cleanup_before_timeout_terminalization(
    monkeypatch, trigger
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    started = threading.Event()
    cleanup_done = threading.Event()
    terminalize_started = threading.Event()
    terminal_sources: list[FlowRunLifecycleSource] = []
    ordering: list[str] = []
    real_run_coroutine_threadsafe = asyncio.run_coroutine_threadsafe

    async def _execute_async(**_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
            ordering.append("cleanup_done")
            cleanup_done.set()
            raise

    async def _terminalize_failure(*, source, **_kwargs):
        ordering.append("terminalize_start")
        terminalize_started.set()
        terminal_sources.append(source)

    monkeypatch.setattr(tasks_module, "_execute_flow_run_async", _execute_async)
    monkeypatch.setattr(
        tasks_module, "terminalize_flow_run_failure", _terminalize_failure
    )
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: loop)
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: SimpleNamespace(flow_task_timeout_seconds=0.01),
    )
    calls = {"count": 0}

    class _SoftLimitFuture:
        def __init__(self, future):
            self._future = future

        def cancel(self):
            return self._future.cancel()

        def result(self, timeout=None):
            raise tasks_module.SoftTimeLimitExceeded()

    def _run_coroutine_threadsafe(coroutine, target_loop):
        future = real_run_coroutine_threadsafe(coroutine, target_loop)
        call_count = calls["count"]
        calls["count"] += 1
        if trigger == "soft_time_limit" and call_count == 0:
            assert started.wait(timeout=1)
            return _SoftLimitFuture(future)
        return future

    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )

    try:
        result = tasks_module._execute_flow_run_task(
            run_id=str(uuid4()),
            flow_id=str(uuid4()),
            tenant_id=str(uuid4()),
            run_revision=1,
            principal_type="user",
            principal_user_id=str(uuid4()),
            task_id="task-1",
            retry_count=0,
        )

        assert result == {"status": "failed", "reason": "timeout"}
        assert terminalize_started.wait(timeout=1)
        assert cleanup_done.wait(timeout=1)
        assert ordering == ["cleanup_done", "terminalize_start"]
        assert terminal_sources == [FlowRunLifecycleSource.TASK_TIMEOUT]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=1)
        loop.close()


def test_execute_flow_run_cancels_uncaptured_future_before_timeout_terminalization(
    monkeypatch,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    pending_future: concurrent.futures.Future[dict[str, str]] | None = None
    terminalize_saw_cancelled: list[bool] = []
    terminal_sources: list[FlowRunLifecycleSource] = []

    class _PendingExecutionFuture(concurrent.futures.Future[dict[str, str]]):
        def __init__(
            self, coroutine: Coroutine[object, object, dict[str, str]]
        ) -> None:
            super().__init__()
            self._coroutine = coroutine
            self._closed = False

        def cancel(self) -> bool:
            self.close_coroutine()
            return super().cancel()

        def close_coroutine(self) -> None:
            if self._closed:
                return
            # Test hygiene only; production closes through asyncio cancellation.
            self._coroutine.close()
            self._closed = True

    def _run_coroutine_threadsafe(
        coroutine: Coroutine[object, object, dict[str, str]], _loop: object
    ) -> _PendingExecutionFuture:
        nonlocal pending_future
        future = _PendingExecutionFuture(coroutine)
        pending_future = future
        return future

    def _terminalize_from_task(*, source: FlowRunLifecycleSource, **_kwargs) -> None:
        assert pending_future is not None
        terminalize_saw_cancelled.append(pending_future.cancelled())
        terminal_sources.append(source)

    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())
    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )
    monkeypatch.setattr(
        tasks_module,
        "_terminalize_flow_run_failure_from_task",
        _terminalize_from_task,
    )
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: SimpleNamespace(flow_task_timeout_seconds=0.01),
    )

    try:
        result = tasks_module._execute_flow_run_task(
            run_id=str(uuid4()),
            flow_id=str(uuid4()),
            tenant_id=str(uuid4()),
            run_revision=1,
            principal_type="user",
            principal_user_id=str(uuid4()),
            task_id="task-1",
            retry_count=0,
        )
    finally:
        if isinstance(pending_future, _PendingExecutionFuture):
            pending_future.close_coroutine()

    assert result == {"status": "failed", "reason": "timeout"}
    assert terminalize_saw_cancelled == [True]
    assert terminal_sources == [FlowRunLifecycleSource.TASK_TIMEOUT]


@pytest.mark.parametrize(
    "wrapper_name",
    [
        "reconcile_stale_running_runs",
        "reconcile_expired_review_checkpoints",
        "redispatch_stale_queued_runs",
        "deliver_flow_audit_outbox",
        "deliver_flow_webhook_outbox",
    ],
)
def test_flow_maintenance_task_wrappers_cancel_future_on_timeout(
    monkeypatch,
    wrapper_name,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    expected_timeout_seconds = {
        "reconcile_stale_running_runs": 30,
        "reconcile_expired_review_checkpoints": 30,
        "redispatch_stale_queued_runs": 60,
        "deliver_flow_audit_outbox": 30,
        "deliver_flow_webhook_outbox": (
            tasks_module.FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS + 30
        ),
    }[wrapper_name]
    captured_coroutines: list[Coroutine[object, object, dict[str, int | str]]] = []

    class _TimeoutThenCancelledFuture(concurrent.futures.Future[dict[str, int | str]]):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_calls = 0
            self.result_timeouts: list[float | None] = []

        def cancel(self) -> bool:
            self.cancel_calls += 1
            return True

        def result(self, timeout: float | None = None) -> dict[str, int | str]:
            self.result_timeouts.append(timeout)
            if len(self.result_timeouts) == 1:
                raise concurrent.futures.TimeoutError()
            raise concurrent.futures.CancelledError()

    future = _TimeoutThenCancelledFuture()

    def _run_coroutine_threadsafe(
        coroutine: Coroutine[object, object, dict[str, int | str]],
        _loop: object,
    ) -> _TimeoutThenCancelledFuture:
        captured_coroutines.append(coroutine)
        return future

    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())
    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )

    try:
        with pytest.raises(concurrent.futures.TimeoutError):
            getattr(tasks_module, wrapper_name)()
    finally:
        for coroutine in captured_coroutines:
            coroutine.close()

    assert future.cancel_calls == 1
    assert future.result_timeouts == [
        expected_timeout_seconds,
        tasks_module._FLOW_TASK_CANCEL_DRAIN_TIMEOUT_SECONDS,
    ]


@pytest.mark.parametrize(
    ("payload", "scheduled_exceptions", "expected_result", "expected_source"),
    [
        (
            {"principal_type": "user", "principal_user_id": str(uuid4())},
            [
                concurrent.futures.TimeoutError(),
                RuntimeError("terminalizer unavailable"),
            ],
            {"status": "failed", "reason": "timeout"},
            FlowRunLifecycleSource.TASK_TIMEOUT,
        ),
        (
            {"principal_type": "user", "principal_user_id": str(uuid4())},
            [RuntimeError("execution failed"), concurrent.futures.TimeoutError()],
            {"status": "failed", "reason": "task_failure"},
            FlowRunLifecycleSource.TASK_FAILURE,
        ),
    ],
)
def test_execute_flow_run_returns_failed_when_task_terminalization_fails(
    monkeypatch,
    payload,
    scheduled_exceptions,
    expected_result,
    expected_source,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    terminalize_failure = AsyncMock()
    execute_async = AsyncMock()
    logger = MagicMock()
    monkeypatch.setattr(
        tasks_module,
        "terminalize_flow_run_failure",
        terminalize_failure,
    )
    monkeypatch.setattr(tasks_module, "_execute_flow_run_async", execute_async)
    monkeypatch.setattr(tasks_module, "_get_flow_task_loop", lambda: object())
    monkeypatch.setattr(tasks_module, "logger", logger)
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: type(
            "_Settings",
            (),
            {"flow_task_timeout_seconds": 1, "flow_max_inline_text_bytes": 1024},
        )(),
    )
    exceptions = deque(scheduled_exceptions)

    class _Future:
        def __init__(self, exception):
            self._exception = exception

        def cancel(self):
            return None

        def result(self, timeout=None):
            raise self._exception

    def _run_coroutine_threadsafe(coroutine, _loop):
        coroutine.close()
        return _Future(exceptions.popleft())

    monkeypatch.setattr(
        tasks_module.asyncio,
        "run_coroutine_threadsafe",
        _run_coroutine_threadsafe,
    )
    base_payload = {
        "run_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "run_revision": 1,
        "task_id": "task-1",
        "retry_count": 0,
    }
    base_payload.update(payload)

    result = tasks_module._execute_flow_run_task(**base_payload)

    assert result == expected_result
    assert terminalize_failure.call_args.kwargs["source"] == expected_source
    logger.exception.assert_called()


def test_execute_flow_run_handles_generic_exception(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
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
        run_revision=1,
        principal_type="user",
        principal_user_id=str(uuid4()),
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
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant_one = SimpleNamespace(id=uuid4())
    tenant_two = SimpleNamespace(id=uuid4())
    run_one = SimpleNamespace(id=uuid4(), tenant_id=tenant_one.id)
    run_two = SimpleNamespace(id=uuid4(), tenant_id=tenant_two.id)
    events: list[str] = []
    repo = MagicMock()
    tenant_repo = MagicMock()

    async def get_all_tenants():
        events.append("get_tenants")
        return [tenant_one, tenant_two]

    async def list_stale_running_runs(*, tenant_id, **_kwargs):
        events.append(f"list:{tenant_id}")
        if tenant_id == tenant_one.id:
            return [run_one]
        return [run_two]

    tenant_repo.get_all_tenants = AsyncMock(side_effect=get_all_tenants)
    repo.list_stale_running_runs = AsyncMock(side_effect=list_stale_running_runs)
    terminalizer = MagicMock()

    async def terminalize_stale_running_run(*, run_id, **_kwargs):
        events.append(f"terminalize:{run_id}")
        return SimpleNamespace(did_transition=True)

    terminalizer.terminalize_stale_running_run = AsyncMock(
        side_effect=terminalize_stale_running_run
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

    fake_session = _fake_flow_task_session(events)

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

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
    assert fake_session.sync_session.autobegin is True
    assert events == [
        "begin",
        "get_tenants",
        "commit",
        "begin",
        f"list:{tenant_one.id}",
        "commit",
        "begin",
        f"terminalize:{run_one.id}",
        "commit",
        "begin",
        f"list:{tenant_two.id}",
        "commit",
        "begin",
        f"terminalize:{run_two.id}",
        "commit",
    ]
    assert terminalizer.terminalize_stale_running_run.await_count == 2
    assert {
        call.kwargs["error"].code
        for call in terminalizer.terminalize_stale_running_run.await_args_list
    } == {"flow_worker_stalled"}
    assert {
        call.kwargs["error"].message
        for call in terminalizer.terminalize_stale_running_run.await_args_list
    } == {
        "flow_worker_stalled: Flow run exceeded the execution timeout and was reconciled as failed."
    }


def test_reconcile_stale_running_task_skips_already_reconciled_runs(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    stale_run = SimpleNamespace(id=uuid4(), tenant_id=tenant.id)
    repo = MagicMock()
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant])
    repo.list_stale_running_runs = AsyncMock(return_value=[stale_run])
    terminalizer = MagicMock()
    terminalizer.terminalize_stale_running_run = AsyncMock(
        return_value=SimpleNamespace(did_transition=False)
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
    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: SimpleNamespace(flow_task_timeout_seconds=540),
    )

    result = asyncio.run(tasks_module._reconcile_stale_running_runs_all_tenants())

    assert result["status"] == "ok"
    assert result["reconciled"] == 0
    assert fake_session.sync_session.autobegin is True
    terminalizer.terminalize_stale_running_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_stale_running_run.await_args.kwargs
    assert terminal_kwargs["error"].code == "flow_worker_stalled"
    assert terminal_kwargs["error"].message == (
        "flow_worker_stalled: Flow run exceeded the execution timeout and was reconciled as failed."
    )


def test_reconcile_review_expiry_task_processes_all_tenants(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
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
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant_one = SimpleNamespace(id=uuid4())
    tenant_two = SimpleNamespace(id=uuid4())
    user_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant_one.id,
        revision=2,
    )
    service_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant_two.id,
        revision=4,
    )
    repo = MagicMock()
    repo.list_dispatchable_queued_runs = AsyncMock(
        side_effect=[[user_run], [service_run]]
    )
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant_one, tenant_two])
    dispatch = AsyncMock(
        side_effect=[
            FlowRunDispatchAccepted(run=user_run),
            FlowRunDispatchAccepted(run=service_run),
        ]
    )

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

    fake_session = _fake_flow_task_session()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result["status"] == "ok"
    assert result["redispatched"] == 2
    assert dispatch.await_args_list[0].kwargs == {
        "run_id": user_run.id,
        "tenant_id": tenant_one.id,
        "expected_revision": 2,
    }
    assert dispatch.await_args_list[1].kwargs == {
        "run_id": service_run.id,
        "tenant_id": tenant_two.id,
        "expected_revision": 4,
    }


def test_redispatch_stale_queued_skips_runs_lost_to_concurrent_claim(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    stale_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        revision=1,
    )
    repo = MagicMock()
    repo.list_dispatchable_queued_runs = AsyncMock(return_value=[stale_run])
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant])
    dispatch = AsyncMock(return_value=FlowRunDispatchNotClaimed(run=stale_run))

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

    fake_session = _fake_flow_task_session()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result["redispatched"] == 0
    dispatch.assert_awaited_once()


def test_redispatch_stale_queued_continues_after_dispatch_error(monkeypatch):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    failed_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        revision=1,
    )
    successful_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        revision=2,
    )
    repo = MagicMock()
    repo.list_dispatchable_queued_runs = AsyncMock(
        return_value=[failed_run, successful_run]
    )
    tenant_repo = MagicMock()
    tenant_repo.get_all_tenants = AsyncMock(return_value=[tenant])
    dispatch = AsyncMock(
        side_effect=[
            FlowRunDispatchFailed(run=failed_run),
            FlowRunDispatchAccepted(run=successful_run),
        ]
    )

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

    fake_session = _fake_flow_task_session()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result == {"status": "ok", "redispatched": 1}
    assert dispatch.await_count == 2


def test_flow_worker_process_init_initializes_observability_db_and_http_client(
    monkeypatch,
):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    events: list[str] = []

    def init_observability():
        events.append("otel")

    def init_db(database_url: str):
        events.append(f"db:{database_url}")

    def start_http_client():
        events.append("aiohttp")

    monkeypatch.setattr(
        celery_app_module,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://db"),
    )
    monkeypatch.setattr(celery_app_module, "init_observability", init_observability)
    monkeypatch.setattr(celery_app_module.sessionmanager, "init", init_db)
    monkeypatch.setattr(celery_app_module.aiohttp_client, "start", start_http_client)
    monkeypatch.setattr(celery_app_module.aiohttp_client, "session", None)

    celery_app_module._on_flow_worker_process_init()

    assert events == ["otel", "db:postgresql+asyncpg://db", "aiohttp"]


def test_flow_worker_process_shutdown_closes_resources(monkeypatch):
    celery_app_module = importlib.import_module("eneo.flows.runtime.celery_app")
    close_mock = MagicMock()
    monkeypatch.setattr(celery_app_module, "_close_flow_worker_resources", close_mock)

    celery_app_module._on_flow_worker_process_shutdown()

    close_mock.assert_called_once_with()


def test_enable_autobegin_for_flow_task_session():
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    sync_session = SimpleNamespace(autobegin=False)
    async_session = SimpleNamespace(sync_session=sync_session)

    tasks_module.enable_autobegin_for_flow_task_session(async_session)

    assert sync_session.autobegin is True


def test_flow_run_logging_context_sets_flow_trace_attributes_and_clears():
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    request_context_module = importlib.import_module("eneo.main.request_context")
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    run_trace_id = uuid4()

    request_context_module.clear_request_context()

    with tasks_module._flow_run_logging_context(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        run_trace_id=run_trace_id,
        celery_task_id="task-1",
    ):
        context = request_context_module.get_request_context()

    assert context["flow.run.id"] == str(run_id)
    assert context["flow.run.trace_id"] == str(run_trace_id)
    assert context["flow.id"] == str(flow_id)
    assert context["flow.tenant.id"] == str(tenant_id)
    assert context["flow.celery.task_id"] == "task-1"
    assert "trace_id" not in context
    assert request_context_module.get_request_context() == {}


def test_redispatch_due_list_transaction_closes_before_dispatch_coordinator(
    monkeypatch,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    tenant = SimpleNamespace(id=uuid4())
    stale_run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=tenant.id,
        revision=3,
    )
    events: list[str] = []
    repo = MagicMock()

    async def list_due(**_kwargs):
        events.append("list_due")
        return [stale_run]

    repo.list_dispatchable_queued_runs = list_due
    tenant_repo = MagicMock()

    async def get_all_tenants():
        events.append("get_tenants")
        return [tenant]

    tenant_repo.get_all_tenants = get_all_tenants

    async def dispatch(**_kwargs):
        events.append("dispatch")
        return FlowRunDispatchAccepted(run=stale_run)

    class _Container:
        def __init__(self, session=None):
            self._repo = repo
            self._tenant_repo = tenant_repo

        def flow_run_repo(self):
            return self._repo

        def tenant_repo(self):
            return self._tenant_repo

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
        tasks_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = asyncio.run(tasks_module._redispatch_stale_queued_runs_all_tenants())

    assert result == {"status": "ok", "redispatched": 1}
    assert sync_session.autobegin is True
    list_idx = events.index("list_due")
    dispatch_idx = events.index("dispatch")
    commits_between = [
        i for i, e in enumerate(events) if e == "commit" and list_idx < i < dispatch_idx
    ]
    assert commits_between, events


@pytest.mark.asyncio
async def test_webhook_outbox_overlaps_rows_with_distinct_sessions_and_services(
    monkeypatch: pytest.MonkeyPatch,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    delivery_module = importlib.import_module(
        "eneo.flows.runtime.flow_webhook_delivery"
    )
    rows = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    sessions: list[object] = []
    services: list[object] = []
    active_deliveries = 0
    peak_deliveries = 0
    both_started = asyncio.Event()

    class _SessionContext:
        async def __aenter__(self):
            session = _fake_flow_task_session()
            sessions.append(session)
            return session

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Service:
        def __init__(self, session):
            self.session = session
            services.append(self)

        async def claim_due_batch(self, **_kwargs):
            return delivery_module.FlowWebhookDeliveryBatch(
                claimed_rows=rows,
                result=delivery_module.FlowWebhookDeliveryResult(),
            )

        async def deliver_claimed(self, *, row, **_kwargs):
            nonlocal active_deliveries, peak_deliveries
            active_deliveries += 1
            peak_deliveries = max(peak_deliveries, active_deliveries)
            if active_deliveries == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            active_deliveries -= 1
            if row.id == rows[0].id:
                return delivery_module.FlowWebhookDeliveryResult(
                    attempted_count=1,
                    delivered_count=1,
                )
            return delivery_module.FlowWebhookDeliveryResult(
                attempted_count=1,
                retry_scheduled_count=1,
            )

    class _Container:
        def __init__(self, *, session):
            self.session = session()

        def flow_run_webhook_delivery_service(self):
            return _Service(self.session)

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = await tasks_module._deliver_flow_webhook_outbox(limit=2)

    assert result == {
        "status": "ok",
        "attempted": 2,
        "delivered": 1,
        "retry_scheduled": 1,
        "dead_lettered": 0,
    }
    assert peak_deliveries == 2
    assert len(sessions) == 3
    assert len({id(session) for session in sessions}) == 3
    assert len(services) == 3
    assert len({id(service) for service in services}) == 3


@pytest.mark.asyncio
async def test_webhook_outbox_worker_exception_does_not_cancel_sibling(
    monkeypatch: pytest.MonkeyPatch,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    delivery_module = importlib.import_module(
        "eneo.flows.runtime.flow_webhook_delivery"
    )
    rows = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    both_started = asyncio.Event()
    started_rows: set[object] = set()
    completed_rows: set[object] = set()

    class _SessionContext:
        async def __aenter__(self):
            return _fake_flow_task_session()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Service:
        async def claim_due_batch(self, **_kwargs):
            return delivery_module.FlowWebhookDeliveryBatch(
                claimed_rows=rows,
                result=delivery_module.FlowWebhookDeliveryResult(),
            )

        async def deliver_claimed(self, *, row, **_kwargs):
            started_rows.add(row.id)
            if len(started_rows) == len(rows):
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            if row.id == rows[0].id:
                raise RuntimeError("worker failed")
            completed_rows.add(row.id)
            return delivery_module.FlowWebhookDeliveryResult(
                attempted_count=1,
                delivered_count=1,
            )

    class _Container:
        def __init__(self, *, session):
            pass

        def flow_run_webhook_delivery_service(self):
            return _Service()

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    result = await tasks_module._deliver_flow_webhook_outbox(limit=2)

    assert started_rows == {row.id for row in rows}
    assert completed_rows == {rows[1].id}
    assert result == {
        "status": "ok",
        "attempted": 2,
        "delivered": 1,
        "retry_scheduled": 0,
        "dead_lettered": 0,
    }


@pytest.mark.asyncio
async def test_webhook_outbox_cancellation_drains_all_delivery_workers(
    monkeypatch: pytest.MonkeyPatch,
):
    tasks_module = importlib.import_module("eneo.flows.runtime.tasks")
    delivery_module = importlib.import_module(
        "eneo.flows.runtime.flow_webhook_delivery"
    )
    rows = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    both_started = asyncio.Event()
    cancelled_rows: set[object] = set()
    started_rows: set[object] = set()

    class _SessionContext:
        async def __aenter__(self):
            return _fake_flow_task_session()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Service:
        async def claim_due_batch(self, **_kwargs):
            return delivery_module.FlowWebhookDeliveryBatch(
                claimed_rows=rows,
                result=delivery_module.FlowWebhookDeliveryResult(),
            )

        async def deliver_claimed(self, *, row, **_kwargs):
            started_rows.add(row.id)
            if len(started_rows) == len(rows):
                both_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_rows.add(row.id)
                raise

    class _Container:
        def __init__(self, *, session):
            pass

        def flow_run_webhook_delivery_service(self):
            return _Service()

    monkeypatch.setattr(tasks_module, "Container", _Container)
    monkeypatch.setattr(
        tasks_module.sessionmanager, "session", lambda: _SessionContext()
    )

    cadence = asyncio.create_task(tasks_module._deliver_flow_webhook_outbox(limit=2))
    await asyncio.wait_for(both_started.wait(), timeout=1)
    cadence.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cadence

    assert cancelled_rows == started_rows == {row.id for row in rows}
