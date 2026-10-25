from __future__ import annotations

import ast
import asyncio
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.execution_backend import FlowExecutionDispatchRejected
from eneo.flows.flow_run_dispatch_request import (
    FlowRunUserDispatchRequest,
    flow_run_dispatch_task_kwargs,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner
from eneo.flows.runtime.execution_heartbeat import FlowExecutionHeartbeats
from eneo.flows.runtime.platform_execution_backend import PlatformFlowExecutionBackend
from eneo.main.config import get_settings
from eneo.main.exceptions import NotReadyException
from eneo.tasks.arq_adapter import ArqTaskEnqueuer
from eneo.tasks.contracts import (
    TaskCapacityClass,
    TaskEnqueueRequest,
    TaskEnqueueResult,
    TaskEnqueueStatus,
)
from eneo.tasks.routing import (
    FLOW_DELIVER_AUDIT_OUTBOX_TASK,
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    FLOW_DRAIN_RETIRED_RUNS_TASK,
    FLOW_EXECUTE_TASK,
    FLOW_RECONCILE_REVIEW_EXPIRY_TASK,
    FLOW_RECONCILE_RUNNING_TASK,
    FLOW_REDISPATCH_STALE_QUEUED_TASK,
    TASK_CAPACITY_BY_NAME,
    task_queue_routing,
)
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
    # Every recovery and delivery job is scheduled on the maintenance worker:
    # stale running runs, expired reviews, lost queued deliveries, retired
    # runs, and the audit and webhook outboxes.
    maintenance_jobs = [job.name for job in PlatformMaintenanceWorkerSettings.cron_jobs]
    assert sorted(maintenance_jobs) == sorted(
        [
            FLOW_RECONCILE_RUNNING_TASK,
            FLOW_RECONCILE_REVIEW_EXPIRY_TASK,
            FLOW_REDISPATCH_STALE_QUEUED_TASK,
            FLOW_DRAIN_RETIRED_RUNS_TASK,
            FLOW_DELIVER_AUDIT_OUTBOX_TASK,
            FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
        ]
    )
    for name in maintenance_jobs:
        assert TASK_CAPACITY_BY_NAME[name] is TaskCapacityClass.MAINTENANCE, name
    assert PlatformExecutionWorkerSettings.queue_name != (
        PlatformMaintenanceWorkerSettings.queue_name
    )
    assert PlatformExecutionWorkerSettings.max_jobs > 0
    assert PlatformMaintenanceWorkerSettings.max_jobs > 0


def test_retired_run_drain_runs_at_the_configured_cadence() -> None:
    [drain] = [
        job
        for job in PlatformMaintenanceWorkerSettings.cron_jobs
        if job.name == FLOW_DRAIN_RETIRED_RUNS_TASK
    ]
    interval = get_settings().flow_retired_run_drain_interval_seconds
    assert drain.second == set(range(0, 60, interval))
    assert TASK_CAPACITY_BY_NAME[FLOW_DRAIN_RETIRED_RUNS_TASK] is (
        TaskCapacityClass.MAINTENANCE
    )


def test_audit_outbox_cron_runs_at_its_delivery_interval() -> None:
    from eneo.flows.application import flow_run_audit_outbox_policy as policy

    [audit] = [
        job
        for job in PlatformMaintenanceWorkerSettings.cron_jobs
        if job.name == FLOW_DELIVER_AUDIT_OUTBOX_TASK
    ]

    assert audit.second == set(
        range(0, 60, policy.FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS)
    )


@pytest.mark.parametrize(
    ("maintenance_timeout_seconds", "drain_seconds"),
    [(get_settings().task_maintenance_timeout_seconds, 30), (3600, 30), (20, 10)],
)
def test_audit_outbox_drain_ends_well_before_the_job_timeout_and_the_next_tick(
    monkeypatch: pytest.MonkeyPatch,
    maintenance_timeout_seconds: float,
    drain_seconds: float,
) -> None:
    """Kills: a drain bounded only by the job timeout, which at the default
    timeout runs a job under a backlog into the next tick, so two audit jobs
    hold both maintenance slots and delay the other maintenance crons."""
    from eneo.flows.application import flow_run_audit_outbox_policy as policy

    monkeypatch.setattr(
        policy,
        "get_settings",
        lambda: SimpleNamespace(
            task_maintenance_timeout_seconds=maintenance_timeout_seconds
        ),
    )

    assert policy.flow_audit_outbox_drain_seconds() == drain_seconds


def test_webhook_outbox_cron_is_one_job_that_stops_itself_before_arq_cancels_it() -> (
    None
):
    """Kills: the webhook cron left on the maintenance default timeout, which
    cancels the job before its deadline with unsent rows still charged; and
    the cron without its fixed job id or with a kept result, so ticks queue
    overlapping jobs or are skipped after a job ended; and the maintenance
    worker keeping a failed job's result (an hour by default), which skips
    every webhook tick once a job killed mid-run is recorded as failed."""
    from eneo.flows.application import flow_webhook_delivery_policy as policy

    [webhook] = [
        job
        for job in PlatformMaintenanceWorkerSettings.cron_jobs
        if job.name == FLOW_DELIVER_WEBHOOK_OUTBOX_TASK
    ]
    budget = policy.flow_webhook_delivery_budget()

    assert webhook.timeout_s == budget.job_timeout_seconds
    assert webhook.second == set(
        range(0, 60, policy.FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS)
    )
    assert webhook.job_id == FLOW_DELIVER_WEBHOOK_OUTBOX_TASK
    assert webhook.keep_result_s == 0
    assert not webhook.keep_result_forever
    assert PlatformMaintenanceWorkerSettings.keep_result == 0


@pytest.mark.parametrize("max_request_timeout_seconds", [1, 120, 600])
def test_webhook_budget_fits_a_maximal_delivery_inside_the_job_and_its_claim(
    max_request_timeout_seconds: float,
) -> None:
    """Kills: a deadline that admits no full delivery at the maximum request
    timeout after the last claim, sends that may end inside the time kept to
    record them, a hard stop that ARQ's timeout does not exceed, and a claim
    that can expire while its job still runs."""
    from eneo.flows.application import flow_webhook_delivery_policy as policy

    budget = policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=max_request_timeout_seconds
    )
    started_at = 1000.0
    deadline = budget.deadline(started_at=started_at)
    last_claim_at = started_at + budget.claim_window_seconds

    assert budget.claim_ttl_seconds >= budget.job_timeout_seconds
    assert deadline.ends_at < deadline.hard_stop_at
    assert deadline.hard_stop_at < started_at + budget.job_timeout_seconds
    assert deadline.allows_new_wave(last_claim_at)
    assert not deadline.allows_new_wave(last_claim_at + 0.5)
    assert (
        deadline.sends_end_at - last_claim_at
        >= budget.preparation_margin_seconds + max_request_timeout_seconds
    )
    assert deadline.ends_at - deadline.sends_end_at >= budget.persistence_margin_seconds


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


def _job_heartbeats(monkeypatch, tasks) -> FlowExecutionHeartbeats:
    """The job's own heartbeats: a job ends only the run it claimed and
    tracks, so a stand-in for a running job tracks its run here too."""
    heartbeats = FlowExecutionHeartbeats(max_active=1)
    monkeypatch.setattr(tasks, "execution_heartbeats", lambda: heartbeats)
    return heartbeats


async def test_execute_task_cancels_before_timeout_terminalization(monkeypatch) -> None:
    from eneo.flows.runtime import tasks

    ordering: list[str] = []
    errors = []
    heartbeats = _job_heartbeats(monkeypatch, tasks)

    async def execute(
        *, run_id: UUID, tenant_id: UUID, run_revision: int, **_kwargs: object
    ) -> dict[str, str]:
        async with heartbeats.track(
            FlowRunExecutionOwner(run_id, tenant_id, run_revision)
        ):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                ordering.append("execution_cancelled")
                raise
        return {"status": "completed"}

    async def terminalize(**kwargs: object) -> None:
        ordering.append(f"terminalize:{kwargs['source']}")
        errors.append(kwargs["error"])

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
    assert errors[0].code.value == "flow_task_timeout"
    assert errors[0].details is None
    assert errors[0].retryable is False
    await heartbeats.stop()


async def test_execute_task_passes_its_existing_invocation_deadline(monkeypatch):
    from eneo.flows.runtime import tasks

    invocation_timeout = asyncio.timeout(600)
    monkeypatch.setattr(tasks.asyncio, "timeout", lambda seconds: invocation_timeout)
    execute = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr(tasks, "_execute_flow_run_async", execute)

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

    assert result == {"status": "completed"}
    assert execute.await_args.kwargs["invocation_deadline"] == invocation_timeout.when()


async def test_registered_worker_leaves_time_to_persist_execution_timeout(
    monkeypatch,
) -> None:
    from arq.worker import Function

    from eneo.flows.runtime import tasks

    function = PlatformExecutionWorkerSettings.functions[0]
    assert isinstance(function, Function)
    worker_timeout = (
        function.timeout_s
        if function.timeout_s is not None
        else PlatformExecutionWorkerSettings.job_timeout
    )
    terminalization_margin = (
        worker_timeout
        - PlatformExecutionWorkerSettings.settings.task_execution_timeout_seconds
    )
    assert terminalization_margin == 60
    # Shorten execution, preserving the registered outer/inner deadline gap.
    execution_timeout = 0.01
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(task_execution_timeout_seconds=execution_timeout),
    )

    heartbeats = _job_heartbeats(monkeypatch, tasks)

    async def execute(
        *, run_id: UUID, tenant_id: UUID, run_revision: int, **_kwargs: object
    ) -> dict[str, str]:
        async with heartbeats.track(
            FlowRunExecutionOwner(run_id, tenant_id, run_revision)
        ):
            await asyncio.Event().wait()
        return {"status": "completed"}

    monkeypatch.setattr(tasks, "_execute_flow_run_async", execute)
    terminalize = AsyncMock()
    monkeypatch.setattr(tasks, "terminalize_flow_run_failure", terminalize)

    result = await asyncio.wait_for(
        function.coroutine(
            {"job_id": str(uuid4())},
            flow_run_dispatch_task_kwargs(_dispatch_request()),
        ),
        timeout=execution_timeout + terminalization_margin,
    )

    assert result == {"status": "failed", "reason": "timeout"}
    terminalize.assert_awaited_once()
    assert (
        terminalize.await_args.kwargs["source"] is FlowRunLifecycleSource.TASK_TIMEOUT
    )
    await heartbeats.stop()


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


async def test_reconciler_uses_one_global_budget_and_advances_after_failure(
    monkeypatch,
):
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta, timezone

    from eneo.flows.domain.flow_run_recovery_policy import FlowRunRecoveryKind
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRecoveryCandidate
    from eneo.flows.runtime import tasks

    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    run = FlowRunRecoveryCandidate(
        id=uuid4(),
        tenant_id=tenant_id,
        revision=3,
        kind=FlowRunRecoveryKind.EXECUTION_HEARTBEAT_EXPIRED,
        anchor_at=now - timedelta(minutes=4),
    )
    repo = AsyncMock()

    repo.list_recovery_candidates.side_effect = [[run], []]
    repo.recovery_sweep_boundary.return_value = (
        run.anchor_at,
        run.id,
    )
    terminalizer = AsyncMock()
    terminalizer.terminalize_stale_running_run.side_effect = RuntimeError("unavailable")
    tenant_repo = AsyncMock()
    tenant_repo.get_all_tenant_ids.return_value = [tenant_id]
    container = SimpleNamespace(
        flow_run_repo=lambda: repo,
        flow_provider_call_repo=lambda: AsyncMock(),
        flow_run_terminalizer=lambda: terminalizer,
        tenant_repo=lambda: tenant_repo,
    )
    session = MagicMock()

    @asynccontextmanager
    async def session_context():
        yield session

    monkeypatch.setattr(tasks.sessionmanager, "session", session_context)
    monkeypatch.setattr(
        tasks, "enable_autobegin_for_flow_task_session", lambda session: None
    )
    monkeypatch.setattr(tasks, "Container", lambda **kwargs: container)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(task_execution_timeout_seconds=14400),
    )
    monkeypatch.setattr(
        tasks,
        "_actionable_recovery",
        tasks._RecoveryWindow(tasks._ACTIONABLE_RECOVERY_KINDS),
    )
    monkeypatch.setattr(
        tasks, "_review_recovery", tasks._RecoveryWindow(tasks._REVIEW_RECOVERY_KINDS)
    )
    with pytest.raises(tasks.FlowTenantSweepPartialFailure):
        await tasks._reconcile_stale_running_runs_all_tenants(limit=1)
    assert repo.list_recovery_candidates.await_args_list[0].kwargs == {
        "limit": 1,
        "after": None,
        "through": (run.anchor_at, run.id),
        "kinds": tasks._ACTIONABLE_RECOVERY_KINDS,
    }
    assert tasks._actionable_recovery.cursor == (run.anchor_at, run.id)
    assert (
        terminalizer.terminalize_stale_running_run.await_args.kwargs[
            "expected_revision"
        ]
        == 3
    )
    tenant_repo.get_all_tenant_ids.assert_not_awaited()


@pytest.mark.parametrize(
    "recovery_kind",
    ["execution_heartbeat_expired", "approved_review", "exhausted_dispatch"],
)
async def test_reconciler_wraps_finite_window_despite_newer_arrivals(
    monkeypatch, recovery_kind
):
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta, timezone
    from uuid import UUID

    from eneo.flows.domain.flow_run_recovery_policy import FlowRunRecoveryKind
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRecoveryCandidate
    from eneo.flows.runtime import tasks

    anchor = datetime.now(timezone.utc) - timedelta(days=31)
    rows = []

    def append_run(number):
        rows.append(
            FlowRunRecoveryCandidate(
                id=UUID(int=number),
                tenant_id=uuid4(),
                revision=1,
                kind=FlowRunRecoveryKind(recovery_kind),
                checkpoint_id=uuid4() if recovery_kind == "approved_review" else None,
                anchor_at=anchor + timedelta(seconds=number),
                cursor_at=(
                    anchor - timedelta(days=5) + timedelta(seconds=number)
                    if recovery_kind == "approved_review"
                    else None
                ),
            )
        )

    def key(row):
        return row.cursor

    append_run(1)
    append_run(2)
    discovered = []

    def of_kinds(kinds):
        actionable = kinds == tasks._ACTIONABLE_RECOVERY_KINDS
        return [
            row
            for row in rows
            if (row.kind in tasks._ACTIONABLE_RECOVERY_KINDS) == actionable
        ]

    async def discover(*, limit, after=None, through=None, kinds):
        candidates = [
            row
            for row in of_kinds(kinds)
            if (after is None or key(row) > after)
            and (through is None or key(row) <= through)
        ][:limit]
        discovered.append(len(candidates))
        return candidates

    repo = AsyncMock()
    repo.list_recovery_candidates.side_effect = discover
    repo.recovery_sweep_boundary.side_effect = lambda *, kinds: max(
        map(key, of_kinds(kinds)), default=None
    )
    attempts = []

    async def terminalize(**kwargs):
        run_id = kwargs["run_id"]
        attempts.append(run_id.int)
        if attempts == [1]:
            raise RuntimeError("transient")
        rows[:] = [row for row in rows if row.id != run_id]
        return SimpleNamespace(did_transition=True)

    terminalizer = AsyncMock()
    terminalizer.terminalize_stale_running_run.side_effect = terminalize
    terminalizer.terminalize_abandoned_run.side_effect = terminalize
    container = SimpleNamespace(
        flow_run_repo=lambda: repo,
        flow_provider_call_repo=lambda: AsyncMock(),
        flow_run_terminalizer=lambda: terminalizer,
    )

    @asynccontextmanager
    async def session_context():
        yield MagicMock()

    monkeypatch.setattr(tasks.sessionmanager, "session", session_context)
    monkeypatch.setattr(tasks, "enable_autobegin_for_flow_task_session", lambda _: None)
    monkeypatch.setattr(tasks, "Container", lambda **_: container)
    monkeypatch.setattr(
        tasks,
        "_actionable_recovery",
        tasks._RecoveryWindow(tasks._ACTIONABLE_RECOVERY_KINDS),
    )
    monkeypatch.setattr(
        tasks, "_review_recovery", tasks._RecoveryWindow(tasks._REVIEW_RECOVERY_KINDS)
    )
    for number in range(3, 9):
        try:
            await tasks._reconcile_stale_running_runs_all_tenants(limit=1)
        except tasks.FlowTenantSweepPartialFailure:
            pass
        append_run(number)
    assert attempts[:3] == [1, 2, 1]
    assert max(discovered) == 1
