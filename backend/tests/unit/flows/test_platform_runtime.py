from __future__ import annotations

import ast
import asyncio
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.execution_backend import FlowExecutionDispatchRejected
from eneo.flows.flow_run_dispatch_request import FlowRunUserDispatchRequest
from eneo.flows.runtime.platform_execution_backend import PlatformFlowExecutionBackend
from eneo.main.exceptions import NotReadyException
from eneo.tasks.arq_adapter import ArqTaskEnqueuer
from eneo.tasks.contracts import (
    TaskCapacityClass,
    TaskEnqueueRequest,
    TaskEnqueueResult,
    TaskEnqueueStatus,
)
from eneo.tasks.routing import FLOW_EXECUTE_TASK, task_queue_routing
from eneo.worker.platform_tasks import (
    PlatformExecutionWorkerSettings,
    PlatformMaintenanceWorkerSettings,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _dispatch_request() -> FlowRunUserDispatchRequest:
    return FlowRunUserDispatchRequest(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        run_revision=3,
        principal_user_id=uuid4(),
    )


async def test_platform_backend_dispatches_with_unique_transport_identity() -> None:
    enqueuer = AsyncMock()
    enqueuer.enqueue.return_value = TaskEnqueueResult(
        status=TaskEnqueueStatus.ACCEPTED,
        task_id=str(uuid4()),
    )
    backend = PlatformFlowExecutionBackend(task_enqueuer=enqueuer)
    request = _dispatch_request()

    await backend.dispatch(request=request)
    await backend.dispatch(request=request)

    first = enqueuer.enqueue.await_args_list[0].args[0]
    second = enqueuer.enqueue.await_args_list[1].args[0]
    assert first.task_name == FLOW_EXECUTE_TASK
    assert first.capacity_class is TaskCapacityClass.EXECUTION
    assert first.idempotency_key != second.idempotency_key
    assert first.payload["tenant_id"] == str(request.tenant_id)


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (TaskEnqueueStatus.REFUSED, FlowExecutionDispatchRejected),
        (TaskEnqueueStatus.OUTCOME_UNKNOWN, RuntimeError),
    ],
)
async def test_platform_backend_preserves_dispatch_outcome_semantics(
    status: TaskEnqueueStatus,
    exception_type: type[Exception],
) -> None:
    enqueuer = AsyncMock()
    enqueuer.enqueue.return_value = TaskEnqueueResult(status=status)
    backend = PlatformFlowExecutionBackend(task_enqueuer=enqueuer)

    with pytest.raises(exception_type):
        await backend.dispatch(request=_dispatch_request())


async def test_arq_adapter_accepts_duplicate_idempotency_key() -> None:
    manager = AsyncMock()
    manager.enqueue_named.return_value = None
    settings = SimpleNamespace(
        task_execution_queue="tasks:execution",
        task_maintenance_queue="tasks:maintenance",
    )
    adapter = ArqTaskEnqueuer(
        job_manager=manager,
        routing=task_queue_routing(settings),
    )
    request = TaskEnqueueRequest(
        task_name=FLOW_EXECUTE_TASK,
        capacity_class=TaskCapacityClass.EXECUTION,
        idempotency_key=str(uuid4()),
        payload={},
    )

    result = await adapter.enqueue(request)

    assert result == TaskEnqueueResult(
        status=TaskEnqueueStatus.ACCEPTED,
        task_id=request.idempotency_key,
    )
    assert manager.enqueue_named.await_args.kwargs["queue_name"] == "tasks:execution"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (NotReadyException("not started"), TaskEnqueueStatus.REFUSED),
        (RedisConnectionError("lost reply"), TaskEnqueueStatus.OUTCOME_UNKNOWN),
    ],
)
async def test_arq_adapter_distinguishes_refusal_from_unknown_outcome(
    failure: Exception,
    expected: TaskEnqueueStatus,
) -> None:
    manager = AsyncMock()
    manager.enqueue_named.side_effect = failure
    routing = MagicMock()
    routing.queue_for.return_value = "tasks:execution"
    adapter = ArqTaskEnqueuer(job_manager=manager, routing=routing)

    result = await adapter.enqueue(
        TaskEnqueueRequest(
            task_name=FLOW_EXECUTE_TASK,
            capacity_class=TaskCapacityClass.EXECUTION,
            idempotency_key=str(uuid4()),
            payload={},
        )
    )

    assert result.status is expected


async def test_arq_adapter_refuses_wrong_capacity_without_enqueueing() -> None:
    manager = AsyncMock()
    adapter = ArqTaskEnqueuer(job_manager=manager, routing=MagicMock())

    result = await adapter.enqueue(
        TaskEnqueueRequest(
            task_name=FLOW_EXECUTE_TASK,
            capacity_class=TaskCapacityClass.MAINTENANCE,
            idempotency_key=str(uuid4()),
            payload={},
        )
    )

    assert result.status is TaskEnqueueStatus.REFUSED
    manager.enqueue_named.assert_not_awaited()


def test_platform_workers_isolate_execution_from_maintenance_capacity() -> None:
    assert [
        function.name for function in PlatformExecutionWorkerSettings.functions
    ] == [FLOW_EXECUTE_TASK]
    assert PlatformExecutionWorkerSettings.cron_jobs == []
    assert PlatformMaintenanceWorkerSettings.functions == []
    assert len(PlatformMaintenanceWorkerSettings.cron_jobs) == 5
    assert PlatformExecutionWorkerSettings.queue_name != (
        PlatformMaintenanceWorkerSettings.queue_name
    )
    assert PlatformExecutionWorkerSettings.max_jobs > 0
    assert PlatformMaintenanceWorkerSettings.max_jobs > 0


def test_flow_layers_are_transport_neutral_and_celery_is_not_a_dependency() -> None:
    flow_root = BACKEND_ROOT / "src" / "eneo" / "flows"
    forbidden_imports: list[str] = []
    for layer in ("domain", "application", "runtime"):
        for path in (flow_root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                imported_roots: list[str] = []
                if isinstance(node, ast.Import):
                    imported_roots = [
                        alias.name.split(".", 1)[0] for alias in node.names
                    ]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots = [node.module.split(".", 1)[0]]
                if {"arq", "celery"} & set(imported_roots):
                    forbidden_imports.append(str(path.relative_to(BACKEND_ROOT)))

    dependencies = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text())[
        "project"
    ]["dependencies"]
    assert forbidden_imports == []
    assert not any(dependency.startswith("celery") for dependency in dependencies)


async def test_execute_task_cancels_before_timeout_terminalization(monkeypatch) -> None:
    from eneo.flows.runtime import tasks

    ordering: list[str] = []

    async def execute(**_kwargs: object) -> dict[str, str]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            ordering.append("execution_cancelled")
            raise

    async def terminalize(**kwargs: object) -> None:
        ordering.append(f"terminalize:{kwargs['source']}")

    monkeypatch.setattr(tasks, "_execute_flow_run_async", execute)
    monkeypatch.setattr(tasks, "terminalize_flow_run_failure", terminalize)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(task_execution_timeout_seconds=0.01),
    )

    result = await tasks.execute_flow_run_task(
        run_id=str(uuid4()),
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="user",
        principal_user_id=str(uuid4()),
        task_id=str(uuid4()),
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "timeout"}
    assert ordering == [
        "execution_cancelled",
        f"terminalize:{FlowRunLifecycleSource.TASK_TIMEOUT}",
    ]


async def test_execute_task_rejects_malformed_payload_without_terminalizing(
    monkeypatch,
) -> None:
    from eneo.flows.runtime import tasks

    terminalize = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(tasks, "terminalize_flow_run_failure", terminalize)
    monkeypatch.setattr(tasks, "_execute_flow_run_async", execute)

    result = await tasks.execute_flow_run_task(
        run_id="invalid",
        flow_id=str(uuid4()),
        tenant_id=str(uuid4()),
        run_revision=1,
        principal_type="user",
        principal_user_id=str(uuid4()),
        task_id=str(uuid4()),
        retry_count=0,
    )

    assert result == {"status": "failed", "reason": "invalid_dispatch_payload"}
    terminalize.assert_not_awaited()
    execute.assert_not_awaited()
