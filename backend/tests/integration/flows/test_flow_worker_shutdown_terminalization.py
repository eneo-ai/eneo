"""A run whose task stops mid-execution (a worker shutdown, a job timeout or
a task failure) fails at once, behind the same execution-owner fence the
heartbeat reaper and the executor write through."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowStepAttempts,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.flow_webhook_delivery import (
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.domain.provider_call import CompletionProviderCallRequest
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.flows.runtime.execution_heartbeat import FlowExecutionHeartbeats
from eneo.main.container.container import Container
from tests.integration.flows.test_flow_provider_call_repository import (
    _create_started_attempt,
    _start_provider_call,
    _StartedAttempt,
)


async def _running_run_with_started_provider_call(
    *, admin_user, completion_model_factory, space_factory, assistant_factory
) -> tuple[_StartedAttempt, FlowRunExecutionOwner, UUID]:
    async with sessionmanager.session() as session, session.begin():
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        call = await _start_provider_call(
            repo=FlowProviderCallRepository(session),
            context=context,
            request=CompletionProviderCallRequest(
                provider_request_hash="c" * 64,
                requested_model="openai/gpt-4o-mini",
                requested_capabilities=(),
            ),
        )
        revision = await session.scalar(
            sa.select(FlowRuns.revision).where(FlowRuns.id == context.run_id)
        )
    assert revision is not None
    return (
        context,
        FlowRunExecutionOwner(context.run_id, context.tenant_id, revision),
        call.id,
    )


async def _persisted(run_id: UUID, call_id: UUID):
    """The run, its provider call, attempts and audit outbox rows, as values."""
    async with sessionmanager.session() as session, session.begin():
        run = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.error_json).where(
                    FlowRuns.id == run_id
                )
            )
        ).one()
        call = (
            await session.execute(
                sa.select(
                    FlowProviderCalls.status, FlowProviderCalls.outcome_reason
                ).where(FlowProviderCalls.id == call_id)
            )
        ).one()
        attempts = (
            await session.execute(
                sa.select(FlowStepAttempts.status, FlowStepAttempts.error_code).where(
                    FlowStepAttempts.flow_run_id == run_id
                )
            )
        ).all()
        outbox = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.source, FlowRunAuditOutbox.error_code
                ).where(FlowRunAuditOutbox.flow_run_id == run_id)
            )
        ).all()
    return run, call, attempts, outbox


@pytest.mark.asyncio
@pytest.mark.integration
async def test_worker_shutdown_fails_the_run_at_once_and_keeps_the_cancellation(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    manager = FlowExecutionHeartbeats(max_active=1)
    monkeypatch.setattr(flow_runtime_tasks, "execution_heartbeats", lambda: manager)
    executing = asyncio.Event()

    async def execute(**_):
        async with manager.track(owner):
            executing.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)

    async def arq_poll() -> None:
        manager.attach_to_worker()
        await asyncio.Event().wait()

    poll = asyncio.create_task(arq_poll())
    job = asyncio.create_task(
        flow_runtime_tasks.execute_flow_run_task(
            run_id=str(owner.run_id),
            flow_id=str(context.flow_id),
            tenant_id=str(owner.tenant_id),
            run_revision=owner.revision,
            principal_type="user",
            principal_user_id=str(context.principal_user_id),
            task_id="shutdown-job",
            retry_count=0,
        )
    )
    await executing.wait()

    # ARQ's order once job_completion_wait is over: the jobs, then its poll task.
    job.cancel()
    poll.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    with pytest.raises(asyncio.CancelledError):
        await poll
    await manager.stop()

    run, call, attempts, outbox = await _persisted(owner.run_id, call_id)
    assert run.status == FlowRunStatus.FAILED.value
    error = FlowRunError.model_validate(run.error_json)
    assert error.code == FlowApiErrorCode.RUN_WORKER_SHUTDOWN
    assert error.source == FlowRunLifecycleSource.TASK_FAILURE
    assert error.retryable is False
    assert [attempt.status for attempt in attempts] == ["failed"]
    assert attempts[0].error_code == FlowApiErrorCode.RUN_WORKER_SHUTDOWN.value
    assert call.status == "outcome_unknown"
    assert call.outcome_reason == "worker_interrupted"
    assert [tuple(row) for row in outbox] == [
        (
            FlowRunLifecycleSource.TASK_FAILURE.value,
            FlowApiErrorCode.RUN_WORKER_SHUTDOWN.value,
        )
    ]


async def _run_after_shutdown_write(
    owner: FlowRunExecutionOwner, call_id: UUID, monkeypatch: pytest.MonkeyPatch
):
    failures = Mock()
    monkeypatch.setattr(flow_runtime_tasks.logger, "exception", failures)
    await flow_runtime_tasks._fail_run_stopped_by_worker_shutdown(
        owner=owner, task_id="shutdown-job"
    )
    # Left alone by the fence, not by a write that failed and was logged.
    failures.assert_not_called()
    return await _persisted(owner.run_id, call_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_shutdown_leaves_a_run_the_user_cancelled(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    _context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    async with sessionmanager.session() as session, session.begin():
        await (
            Container(session=providers.Object(session))
            .flow_run_terminalizer()
            .terminalize_run(
                run_id=owner.run_id,
                tenant_id=owner.tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.USER_CANCEL,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.USER_CANCEL,
                    code=FlowApiErrorCode.RUN_USER_CANCELLED,
                    message="Run cancelled by user.",
                ),
            )
        )

    run, call, _attempts, outbox = await _run_after_shutdown_write(
        owner, call_id, monkeypatch
    )

    assert run.status == FlowRunStatus.CANCELLED.value
    assert run.error_json["code"] == FlowApiErrorCode.RUN_USER_CANCELLED.value
    assert call.status == "started"
    assert [row.source for row in outbox] == [FlowRunLifecycleSource.USER_CANCEL.value]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("lost_by", ["newer_revision", "expired_heartbeat"])
async def test_shutdown_leaves_a_run_this_worker_no_longer_owns(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    lost_by,
):
    _context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == owner.run_id)
            .values(
                revision=FlowRuns.revision + 1
                if lost_by == "newer_revision"
                else FlowRuns.revision,
                execution_heartbeat_at=sa.func.clock_timestamp()
                - sa.text("interval '1 hour'")
                if lost_by == "expired_heartbeat"
                else FlowRuns.execution_heartbeat_at,
            )
        )

    run, call, attempts, outbox = await _run_after_shutdown_write(
        owner, call_id, monkeypatch
    )

    assert run.status == FlowRunStatus.RUNNING.value
    assert run.error_json is None
    assert [attempt.status for attempt in attempts] == ["started"]
    assert call.status == "started"
    assert outbox == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_shutdown_leaves_a_run_waiting_on_webhook_delivery(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    async with sessionmanager.session() as session, session.begin():
        await FlowRunWebhookDeliveryRepository(session=session).insert_pending_delivery(
            flow_id=context.flow_id,
            tenant_id=owner.tenant_id,
            intent=WebhookDeliveryIntent(
                flow_run_id=owner.run_id,
                step_id=context.step_id,
                step_order=1,
                attempt_no=1,
                idempotency_key=f"{owner.run_id}:{context.step_id}:1:webhook",
                payload=WebhookPayloadRef(
                    value=f"flow_run:{owner.run_id}:step:{context.step_id}:attempt:1"
                ),
            ),
        )

    run, call, _attempts, outbox = await _run_after_shutdown_write(
        owner, call_id, monkeypatch
    )

    assert run.status == FlowRunStatus.RUNNING.value
    assert call.status == "started"
    assert outbox == []


# A job timeout and a task failure write after the heartbeat context reset the
# owner too, so they end the run behind the owner the task passes, as the
# shutdown does: a run taken over, under review or handed to a delivery stays.
_TASK_STOPS = {
    "timeout": (
        FlowRunLifecycleSource.TASK_TIMEOUT,
        FlowApiErrorCode.RUN_TASK_TIMEOUT,
        "Flow execution task timed out",
    ),
    "failure": (
        FlowRunLifecycleSource.TASK_FAILURE,
        FlowApiErrorCode.RUN_TASK_FAILURE,
        "Flow execution task failed",
    ),
}


async def _run_task_that_stops(
    *,
    stop: str,
    context,
    owner: FlowRunExecutionOwner,
    monkeypatch,
    claims_the_run: bool = True,
):
    manager = FlowExecutionHeartbeats(max_active=1)
    monkeypatch.setattr(flow_runtime_tasks, "execution_heartbeats", lambda: manager)
    if stop == "timeout":
        monkeypatch.setattr(
            flow_runtime_tasks,
            "get_settings",
            lambda: SimpleNamespace(task_execution_timeout_seconds=0.05),
        )

    async def stop_the_task() -> None:
        if stop == "failure":
            raise RuntimeError("step blew up")
        await asyncio.Event().wait()

    async def execute(**_):
        if not claims_the_run:
            return await stop_the_task()
        async with manager.track(owner):
            await stop_the_task()

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)
    failures = Mock()
    monkeypatch.setattr(flow_runtime_tasks.logger, "exception", failures)
    result = await flow_runtime_tasks.execute_flow_run_task(
        run_id=str(owner.run_id),
        flow_id=str(context.flow_id),
        tenant_id=str(owner.tenant_id),
        run_revision=owner.revision,
        principal_type="user",
        principal_user_id=str(context.principal_user_id),
        task_id=f"{stop}-job",
        retry_count=0,
    )
    await manager.stop()
    assert result == {
        "status": "failed",
        "reason": "timeout" if stop == "timeout" else "task_failure",
    }
    # The task's own failure log only: no terminal write failed.
    assert [entry.args[0] for entry in failures.call_args_list] == [
        _TASK_STOPS[stop][2]
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("stop", ["timeout", "failure"])
async def test_a_timed_out_or_failed_task_fails_the_run_it_owns(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    stop,
):
    context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )

    await _run_task_that_stops(
        stop=stop, context=context, owner=owner, monkeypatch=monkeypatch
    )

    source, code, _log = _TASK_STOPS[stop]
    run, call, attempts, outbox = await _persisted(owner.run_id, call_id)
    assert run.status == FlowRunStatus.FAILED.value
    error = FlowRunError.model_validate(run.error_json)
    assert error.code == code
    assert error.source == source
    assert [(attempt.status, attempt.error_code) for attempt in attempts] == [
        ("failed", code.value)
    ]
    # As after a shutdown or the reaper: the task's started call has no known
    # outcome once the task ended its run.
    assert call.status == "outcome_unknown"
    assert call.outcome_reason == "worker_interrupted"
    assert [tuple(row) for row in outbox] == [(source.value, code.value)]


async def _hand_the_run_elsewhere(held_by: str, context, owner) -> str:
    """Move the run out of this task's hands; return the status it then has."""
    async with sessionmanager.session() as session, session.begin():
        if held_by == "webhook_delivery":
            await FlowRunWebhookDeliveryRepository(
                session=session
            ).insert_pending_delivery(
                flow_id=context.flow_id,
                tenant_id=owner.tenant_id,
                intent=WebhookDeliveryIntent(
                    flow_run_id=owner.run_id,
                    step_id=context.step_id,
                    step_order=1,
                    attempt_no=1,
                    idempotency_key=f"{owner.run_id}:{context.step_id}:1:webhook",
                    payload=WebhookPayloadRef(
                        value=f"flow_run:{owner.run_id}:step:{context.step_id}:attempt:1"
                    ),
                ),
            )
            return FlowRunStatus.RUNNING.value
        status = (
            FlowRunStatus.AWAITING_REVIEW
            if held_by == "review"
            else FlowRunStatus.RUNNING
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == owner.run_id)
            .values(
                status=status.value,
                revision=FlowRuns.revision + int(held_by == "newer_revision"),
            )
        )
        return status.value


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("stop", "held_by"),
    [
        ("timeout", "newer_revision"),
        ("failure", "newer_revision"),
        ("failure", "review"),
        ("failure", "webhook_delivery"),
    ],
)
async def test_a_timed_out_or_failed_task_leaves_a_run_it_no_longer_owns(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    stop,
    held_by,
):
    context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    status = await _hand_the_run_elsewhere(held_by, context, owner)

    await _run_task_that_stops(
        stop=stop, context=context, owner=owner, monkeypatch=monkeypatch
    )

    run, call, attempts, outbox = await _persisted(owner.run_id, call_id)
    assert run.status == status
    assert run.error_json is None
    assert [attempt.status for attempt in attempts] == ["started"]
    assert call.status == "started"
    assert outbox == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("stop", ["timeout", "failure"])
async def test_a_duplicate_task_that_never_claimed_the_run_leaves_it(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    stop,
):
    # Another task holds the run: RUNNING, live heartbeat, this revision. A
    # duplicate delivery of the same revision passes the owner fence, so only
    # its missing claim keeps it from ending that task's run.
    context, owner, call_id = await _running_run_with_started_provider_call(
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )

    await _run_task_that_stops(
        stop=stop,
        context=context,
        owner=owner,
        monkeypatch=monkeypatch,
        claims_the_run=False,
    )

    run, call, attempts, outbox = await _persisted(owner.run_id, call_id)
    assert run.status == FlowRunStatus.RUNNING.value
    assert run.error_json is None
    assert [attempt.status for attempt in attempts] == ["started"]
    assert call.status == "started"
    assert outbox == []
