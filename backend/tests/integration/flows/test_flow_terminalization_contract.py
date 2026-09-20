from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows.application.flow_run_lifecycle_events import (
    FLOW_RUN_LIFECYCLE_EVENT_NAME,
)
from eneo.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationInvariantError,
    FlowRunTerminalizer,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    flow_stale_running_reconcile_after_seconds,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.flows.runtime.step_execution_result import (
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.main.config import get_settings
from tests.flow_snapshot_fixtures import assistant_snapshot


def _stale_run_age() -> timedelta:
    return timedelta(
        seconds=flow_stale_running_reconcile_after_seconds(
            task_timeout_seconds=get_settings().task_execution_timeout_seconds
        )
        + 60
    )


LIFECYCLE_LOGGER = "eneo.flows.application.flow_run_lifecycle_events"


def _flow_run_terminalizer(run_repo: FlowRunRepository) -> FlowRunTerminalizer:
    return FlowRunTerminalizer(
        run_repo,
        run_repo.audit_outbox_repo,
        FlowRunReviewCheckpointRepository(
            session=run_repo.session,
            audit_outbox_repo=run_repo.audit_outbox_repo,
        ),
    )


@contextmanager
def _capture_flow_lifecycle_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    logger = logging.getLogger(LIFECYCLE_LOGGER)
    handler = caplog.handler
    original_disabled = logger.disabled
    original_level = logger.level
    original_propagate = logger.propagate
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def _flow_lifecycle_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == FLOW_RUN_LIFECYCLE_EVENT_NAME
    ]


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Terminalization Contract Flow",
        description="Flow used for terminalization contract tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Step one",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                input_config=None,
                output_config=None,
            ),
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=2,
                user_description="Step two",
                input_source="previous_step",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"summary": "{{step_1.output.text}}"},
                output_classification_override=None,
                input_config=None,
                output_config=None,
            ),
        ],
    )


async def _create_running_run(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    start_attempt=True,
):
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Terminalization contract space", [model.id])
    assistant = await assistant_factory(
        session,
        "Terminalization Contract Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session)
    version_repo = FlowVersionRepository(session=session)
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_json={
            "steps": [
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "assistant_snapshot": assistant_snapshot(step.assistant_id),
                    "step_order": step.step_order,
                }
                for step in flow.steps
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    flow = flow.model_copy(update={"published_version": 1})
    flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)

    run_repo = FlowRunRepository(session=session)
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "What happened?"},
        preseed_steps=[
            {
                "step_id": step.id,
                "assistant_id": step.assistant_id,
                "step_order": step.step_order,
            }
            for step in flow.steps
        ],
    )
    assert await run_repo.mark_running_if_claimable(
        run_id=run.id,
        tenant_id=admin_user.tenant_id,
        expected_revision=run.revision,
    )
    if not start_attempt:
        return run, flow, run_repo
    claimed = await run_repo.claim_step_result(
        run_id=run.id,
        step_id=flow.steps[0].id,
        tenant_id=admin_user.tenant_id,
    )
    assert claimed is not None
    await run_repo.create_or_get_attempt_started(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        step_id=flow.steps[0].id,
        step_order=1,
        attempt_no=1,
        dispatch_task_id="terminalization-contract",
    )
    return run, flow, run_repo


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalization_fails_run_once_and_writes_one_outbox_event(
    caplog: pytest.LogCaptureFixture,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        other_run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "Leave this run alone."},
            preseed_steps=[
                {
                    "step_id": step.id,
                    "assistant_id": step.assistant_id,
                    "step_order": step.step_order,
                }
                for step in flow.steps
            ],
        )
        assert await run_repo.mark_running_if_claimable(
            run_id=other_run.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=other_run.revision,
        )
        other_claimed = await run_repo.claim_step_result(
            run_id=other_run.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )
        assert other_claimed is not None
        await run_repo.create_or_get_attempt_started(
            run_id=other_run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=1,
            dispatch_task_id="terminalization-contract-other-run",
        )
        terminalizer = _flow_run_terminalizer(run_repo)

        with _capture_flow_lifecycle_logs(caplog):
            first = await terminalizer.terminalize_run(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                    code=FlowApiErrorCode.RUN_WORKER_STALLED,
                    message="flow_worker_stalled: stale run reconciled.",
                ),
            )
            second = await terminalizer.terminalize_run(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                    code=FlowApiErrorCode.RUN_WORKER_STALLED,
                    message="flow_worker_stalled: duplicate reconciliation.",
                ),
            )

        assert first.did_transition is True
        assert second.did_transition is False
        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        assert run_row is not None
        assert run_row.status == FlowRunStatus.FAILED.value

        step_statuses = (
            (
                await session.execute(
                    sa.select(FlowStepResults.status)
                    .where(FlowStepResults.flow_run_id == run.id)
                    .order_by(FlowStepResults.step_order)
                )
            )
            .scalars()
            .all()
        )
        assert step_statuses == [
            FlowStepResultStatus.FAILED.value,
            FlowStepResultStatus.FAILED.value,
        ]
        attempt_status = await session.scalar(
            sa.select(FlowStepAttempts.status).where(
                FlowStepAttempts.flow_run_id == run.id
            )
        )
        assert attempt_status == FlowStepAttemptStatus.FAILED.value
        attempt_error_code = await session.scalar(
            sa.select(FlowStepAttempts.error_code).where(
                FlowStepAttempts.flow_run_id == run.id
            )
        )
        assert attempt_error_code == "flow_worker_stalled"
        other_step_statuses = (
            (
                await session.execute(
                    sa.select(FlowStepResults.status)
                    .where(FlowStepResults.flow_run_id == other_run.id)
                    .order_by(FlowStepResults.step_order)
                )
            )
            .scalars()
            .all()
        )
        assert other_step_statuses == [
            FlowStepResultStatus.RUNNING.value,
            FlowStepResultStatus.PENDING.value,
        ]
        other_attempt_status = await session.scalar(
            sa.select(FlowStepAttempts.status).where(
                FlowStepAttempts.flow_run_id == other_run.id
            )
        )
        assert other_attempt_status == FlowStepAttemptStatus.STARTED.value

        outbox_rows = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox).where(
                        FlowRunAuditOutbox.flow_run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox_rows) == 1
        assert (
            outbox_rows[0].source
            == FlowRunLifecycleSource.STALE_RUNNING_RECONCILER.value
        )
        assert outbox_rows[0].action == "flow_run_failed"
        assert outbox_rows[0].description == (
            "flow_run_failed:stale_running_reconciler"
        )
        lifecycle_records = _flow_lifecycle_records(caplog)
        assert [getattr(record, "outcome") for record in lifecycle_records] == [
            "transitioned",
            "noop_already_terminal",
        ]
        success_record = lifecycle_records[0]
        assert getattr(success_record, "run_id") == str(run.id)
        assert getattr(success_record, "tenant_id") == str(admin_user.tenant_id)
        assert (
            getattr(success_record, "source")
            == FlowRunLifecycleSource.STALE_RUNNING_RECONCILER.value
        )
        assert getattr(success_record, "target_status") == FlowRunStatus.FAILED.value
        assert getattr(success_record, "previous_status") == FlowRunStatus.RUNNING.value
        assert getattr(success_record, "trace_id") == str(first.run.trace_id)
        assert getattr(success_record, "audit_outbox_id") == str(first.audit_outbox_id)

        noop_record = lifecycle_records[1]
        assert getattr(noop_record, "target_status") == FlowRunStatus.FAILED.value
        assert getattr(noop_record, "previous_status") == FlowRunStatus.FAILED.value
        assert getattr(noop_record, "audit_outbox_id") is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_running_reconcile_task_commits_failure_for_fresh_sessions(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as setup_session, setup_session.begin():
        run, _flow, _run_repo = await _create_running_run(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        run_id = run.id
        tenant_id = admin_user.tenant_id
        await setup_session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(execution_heartbeat_at=sa.func.clock_timestamp() - _stale_run_age())
        )

    result = await flow_runtime_tasks._reconcile_stale_running_runs_all_tenants(
        limit=10
    )

    assert result["status"] == "ok"
    assert result["reconciled"] >= 1
    async with sessionmanager.session() as verify_session, verify_session.begin():
        run_row = await verify_session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
        )
        assert run_row is not None
        assert run_row.status == FlowRunStatus.FAILED.value
        run_error = FlowRunError.model_validate(run_row.error_json)
        assert run_error.code == FlowApiErrorCode.RUN_WORKER_STALLED.value
        assert run_error.source == FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
        assert run_error.message == (
            "flow_worker_stalled: Flow execution heartbeat expired."
        )

        step_statuses = (
            (
                await verify_session.execute(
                    sa.select(FlowStepResults.status)
                    .where(FlowStepResults.flow_run_id == run_id)
                    .order_by(FlowStepResults.step_order)
                )
            )
            .scalars()
            .all()
        )
        assert step_statuses == [
            FlowStepResultStatus.FAILED.value,
            FlowStepResultStatus.FAILED.value,
        ]
        attempt_statuses = (
            (
                await verify_session.execute(
                    sa.select(FlowStepAttempts.status).where(
                        FlowStepAttempts.flow_run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert attempt_statuses == [FlowStepAttemptStatus.FAILED.value]
        outbox_rows = (
            (
                await verify_session.execute(
                    sa.select(FlowRunAuditOutbox).where(
                        FlowRunAuditOutbox.flow_run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox_rows) == 1
        assert (
            outbox_rows[0].source
            == FlowRunLifecycleSource.STALE_RUNNING_RECONCILER.value
        )
        assert outbox_rows[0].target_status == FlowRunStatus.FAILED.value
        assert outbox_rows[0].error_code == FlowApiErrorCode.RUN_WORKER_STALLED.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failed_terminalization_without_structured_error_closes_attempt_with_null_error_code(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, _flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        terminalizer = _flow_run_terminalizer(run_repo)

        await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.TASK_FAILURE,
        )

        attempt_row = await session.scalar(
            sa.select(FlowStepAttempts).where(FlowStepAttempts.flow_run_id == run.id)
        )
        assert attempt_row is not None
        assert attempt_row.status == FlowStepAttemptStatus.FAILED.value
        assert attempt_row.error_code is None
        assert attempt_row.error_message is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_running_query_excludes_awaiting_review_runs(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, _flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        stale_updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                status=FlowRunStatus.AWAITING_REVIEW.value,
                updated_at=stale_updated_at,
            )
        )

        stale_runs = await run_repo.list_stale_running_runs(
            tenant_id=admin_user.tenant_id,
        )

    assert stale_runs == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pending_webhook_committed_after_stale_discovery_blocks_terminalization(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as setup_session, setup_session.begin():
        run, flow, _run_repo = await _create_running_run(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        await setup_session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .where(FlowRuns.tenant_id == admin_user.tenant_id)
            .values(
                execution_heartbeat_at=sa.func.clock_timestamp() - timedelta(hours=1)
            )
        )
        run_id = run.id
        flow_id = flow.id
        step_id = flow.steps[0].id

    assert flow_id is not None
    assert step_id is not None
    stale_run_discovered = asyncio.Event()
    webhook_committed = asyncio.Event()

    async def discover_then_terminalize():
        async with sessionmanager.session() as recovery_session:
            run_repo = FlowRunRepository(session=recovery_session)
            terminalizer = _flow_run_terminalizer(run_repo)
            async with recovery_session.begin():
                stale_runs = await run_repo.list_stale_running_runs(
                    tenant_id=admin_user.tenant_id,
                )
            assert [candidate.id for candidate in stale_runs] == [run_id]
            stale_run_discovered.set()
            await webhook_committed.wait()
            async with recovery_session.begin():
                return await terminalizer.terminalize_stale_running_run(
                    run_id=run_id,
                    tenant_id=admin_user.tenant_id,
                    expected_revision=run.revision,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                        code=FlowApiErrorCode.RUN_WORKER_STALLED,
                        message="flow_worker_stalled: stale run reconciled.",
                    ),
                )

    async def commit_pending_webhook():
        await stale_run_discovered.wait()
        async with sessionmanager.session() as webhook_session, webhook_session.begin():
            await FlowRunWebhookDeliveryRepository(
                session=webhook_session
            ).insert_pending_delivery(
                flow_id=flow_id,
                tenant_id=admin_user.tenant_id,
                intent=WebhookDeliveryIntent(
                    flow_run_id=run_id,
                    step_id=step_id,
                    step_order=1,
                    attempt_no=1,
                    idempotency_key=f"{run_id}:{step_id}:1:webhook",
                    payload=WebhookPayloadRef(
                        value=f"flow_run:{run_id}:step:{step_id}:attempt:1"
                    ),
                ),
            )
        webhook_committed.set()

    async with asyncio.TaskGroup() as task_group:
        recovery_task = task_group.create_task(discover_then_terminalize())
        task_group.create_task(commit_pending_webhook())
    result = recovery_task.result()

    assert result.did_transition is False
    assert result.run.status is FlowRunStatus.RUNNING
    async with sessionmanager.session() as verify_session, verify_session.begin():
        persisted_status = await verify_session.scalar(
            sa.select(FlowRuns.status)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == admin_user.tenant_id)
        )
        outbox_count = await verify_session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run_id)
        )

    assert persisted_status == FlowRunStatus.RUNNING.value
    assert outbox_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalization_lost_race_emits_noop_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, _flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        monkeypatch.setattr(
            run_repo,
            "terminalize_run_status",
            AsyncMock(return_value=None),
        )
        terminalizer = _flow_run_terminalizer(run_repo)

        with _capture_flow_lifecycle_logs(caplog):
            result = await terminalizer.terminalize_run(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.TASK_FAILURE,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.TASK_FAILURE,
                    code=FlowApiErrorCode.RUN_TASK_FAILURE,
                    message="flow_task_failure: task failed.",
                ),
            )

        assert result.did_transition is False
        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        assert run_row is not None
        assert run_row.status == FlowRunStatus.RUNNING.value
        outbox_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run.id)
        )
        assert outbox_count == 0

        lifecycle_records = _flow_lifecycle_records(caplog)
        assert len(lifecycle_records) == 1
        record = lifecycle_records[0]
        assert getattr(record, "outcome") == "noop_lost_race"
        assert getattr(record, "run_id") == str(run.id)
        assert getattr(record, "source") == FlowRunLifecycleSource.TASK_FAILURE.value
        assert getattr(record, "target_status") == FlowRunStatus.FAILED.value
        assert getattr(record, "previous_status") == FlowRunStatus.RUNNING.value
        assert getattr(record, "audit_outbox_id") is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completed_terminalization_rejects_open_runtime_rows(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, _flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        terminalizer = _flow_run_terminalizer(run_repo)

        with pytest.raises(FlowRunTerminalizationInvariantError):
            await terminalizer.terminalize_run(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                target_status=FlowRunStatus.COMPLETED,
                source=FlowRunLifecycleSource.EXECUTOR_COMPLETED,
                output_payload_json={"text": "done"},
            )

        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        assert run_row is not None
        assert run_row.status == FlowRunStatus.RUNNING.value
        outbox_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run.id)
        )
        assert outbox_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalization_rolls_back_when_audit_outbox_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        run, _flow, run_repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        monkeypatch.setattr(
            run_repo.audit_outbox_repo,
            "insert_terminal_audit_outbox",
            AsyncMock(side_effect=RuntimeError("outbox unavailable")),
        )
        terminalizer = _flow_run_terminalizer(run_repo)

        with _capture_flow_lifecycle_logs(caplog):
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                async with session.begin_nested():
                    await terminalizer.terminalize_run(
                        run_id=run.id,
                        tenant_id=admin_user.tenant_id,
                        target_status=FlowRunStatus.FAILED,
                        source=FlowRunLifecycleSource.TASK_FAILURE,
                        error=FlowRunError.from_source(
                            FlowRunLifecycleSource.TASK_FAILURE,
                            code=FlowApiErrorCode.RUN_TASK_FAILURE,
                            message="flow_task_failure: task failed.",
                        ),
                    )

        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        assert run_row is not None
        assert run_row.status == FlowRunStatus.RUNNING.value
        step_statuses = (
            (
                await session.execute(
                    sa.select(FlowStepResults.status)
                    .where(FlowStepResults.flow_run_id == run.id)
                    .order_by(FlowStepResults.step_order)
                )
            )
            .scalars()
            .all()
        )
        assert step_statuses == [
            FlowStepResultStatus.RUNNING.value,
            FlowStepResultStatus.PENDING.value,
        ]
        outbox_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run.id)
        )
        assert outbox_count == 0
        assert _flow_lifecycle_records(caplog) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tenant_sweeps_survive_a_tenant_row_the_model_refuses(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    # A tenants.state value written outside the code (the column is a free
    # string) must not stop the platform sweep for every other tenant.
    from eneo.database.tables.tenant_table import Tenants

    async with sessionmanager.session() as setup_session, setup_session.begin():
        run, _flow, _run_repo = await _create_running_run(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        run_id = run.id
        tenant_id = admin_user.tenant_id
        await setup_session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(execution_heartbeat_at=sa.func.clock_timestamp() - _stale_run_age())
        )
        await setup_session.execute(
            sa.insert(Tenants).values(
                name="tenant-with-a-state-the-model-refuses",
                state="inactive",
                quota_limit=0,
            )
        )

    result = await flow_runtime_tasks._reconcile_stale_running_runs_all_tenants(
        limit=10
    )

    assert result["status"] == "ok"
    assert result["reconciled"] >= 1
    assert (
        await flow_runtime_tasks._redispatch_stale_queued_runs_all_tenants(limit=10)
    )["status"] == "ok"
    assert (
        await flow_runtime_tasks._reconcile_expired_review_checkpoints_all_tenants(
            limit=10
        )
    )["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_death_after_claim_before_first_attempt_is_recovered(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    async with sessionmanager.session() as session, session.begin():
        run, _, _ = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            start_attempt=False,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                execution_heartbeat_at=sa.func.clock_timestamp()
                - timedelta(seconds=181)
            )
        )
    monkeypatch.setattr(flow_runtime_tasks, "_stale_running_cursor", None)
    await flow_runtime_tasks._reconcile_stale_running_runs_all_tenants()
    async with sessionmanager.session() as session, session.begin():
        recovered = await FlowRunRepository(session=session).get(
            run_id=run.id, tenant_id=run.tenant_id
        )
        assert recovered.status == FlowRunStatus.FAILED
        assert recovered.error.code == FlowApiErrorCode.RUN_WORKER_STALLED
        facts = recovered.error.details.recovery
        assert facts.reason == "execution_heartbeat_expired"
        assert facts.expires_at - facts.heartbeat_at == timedelta(seconds=180)
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run.id)
            )
            == 0
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowRunAuditOutbox)
                .where(FlowRunAuditOutbox.flow_run_id == run.id)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_long_work_renews_but_old_revision_and_expired_owner_cannot(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner

    async with sessionmanager.session() as session, session.begin():
        run, _, repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            start_attempt=False,
        )
        old_updated_at = datetime.now(timezone.utc) - timedelta(hours=5)
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(updated_at=old_updated_at)
        )
    owner = FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
    old_owner = FlowRunExecutionOwner(run.id, run.tenant_id, run.revision - 1)
    for _ in range(3):
        async with sessionmanager.session() as session, session.begin():
            repo = FlowRunRepository(session=session)
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == run.id)
                .values(
                    execution_heartbeat_at=sa.func.clock_timestamp()
                    - timedelta(seconds=170),
                    updated_at=FlowRuns.updated_at,
                )
            )
            assert await repo.renew_execution_heartbeats(owners=[old_owner]) == set()
            assert await repo.renew_execution_heartbeats(owners=[owner]) == {owner}
            renewed = await repo.get(run_id=run.id, tenant_id=run.tenant_id)
            assert renewed.updated_at == old_updated_at
            assert renewed.revision == owner.revision
            assert renewed.execution_heartbeat_at > datetime.now(
                timezone.utc
            ) - timedelta(seconds=10)
            assert run.id not in {
                row.id
                for row in await repo.list_stale_running_runs(tenant_id=run.tenant_id)
            }
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                execution_heartbeat_at=sa.func.clock_timestamp()
                - timedelta(seconds=181)
            )
        )
        assert (
            await FlowRunRepository(session=session).renew_execution_heartbeats(
                owners=[owner]
            )
            == set()
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("expired", [False, True])
async def test_renewal_and_two_recoveries_have_one_terminal_owner(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    expired,
):
    from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner

    async with sessionmanager.session() as session, session.begin():
        run, _, _ = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                execution_heartbeat_at=sa.func.clock_timestamp()
                - timedelta(seconds=181 if expired else 30)
            )
        )
    owner = FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
    barrier = asyncio.Barrier(3)

    async def renew():
        async with sessionmanager.session() as session, session.begin():
            await barrier.wait()
            return await FlowRunRepository(session=session).renew_execution_heartbeats(
                owners=[owner]
            )

    async def recover():
        async with sessionmanager.session() as session, session.begin():
            await barrier.wait()
            return await _flow_run_terminalizer(
                FlowRunRepository(session=session)
            ).terminalize_stale_running_run(
                run_id=run.id,
                tenant_id=run.tenant_id,
                expected_revision=run.revision,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                    code=FlowApiErrorCode.RUN_WORKER_STALLED,
                    message="Execution heartbeat expired.",
                ),
            )

    renewed, first, second = await asyncio.gather(renew(), recover(), recover())
    assert renewed == (set() if expired else {owner})
    assert sum(result.did_transition for result in (first, second)) == int(expired)
    async with sessionmanager.session() as session, session.begin():
        assert await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run.id)
        ) == int(expired)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.migration_isolation
async def test_heartbeat_migration_cutover_preserves_existing_running_history(
    db_container, completion_model_factory, space_factory, assistant_factory, admin_user
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    async with db_container() as container:
        session = container.session()
        run, _, repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            start_attempt=False,
        )
        existing = await repo.get(run_id=run.id, tenant_id=run.tenant_id)
        engine = session.bind
    assert engine is not None
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202609202000_flow_execution_heartbeat.py"
    )
    spec = importlib.util.spec_from_file_location("heartbeat_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def cycle(connection):
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            migration.downgrade()
            assert "execution_heartbeat_at" not in {
                column["name"]
                for column in sa.inspect(connection).get_columns("flow_runs")
            }
            migration.upgrade()

    async with engine.connect() as connection:
        await connection.run_sync(cycle)
    async with sessionmanager.session() as session, session.begin():
        restored = await FlowRunRepository(session=session).get(
            run_id=run.id, tenant_id=run.tenant_id
        )
        assert restored.execution_heartbeat_at == existing.updated_at
        assert restored.updated_at == existing.updated_at
        assert restored.revision == existing.revision
        assert restored.status == existing.status == FlowRunStatus.RUNNING


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "publication", ["transcript", "result", "delivery", "attempt_input"]
)
async def test_paused_provider_publication_cannot_change_recovered_run(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    publication,
):
    from eneo.database.tables.flow_tables import FlowRunWebhookDeliveries
    from eneo.flows.domain.flow_step_attempt_input import FlowStepAttemptInput
    from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
    from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner
    from eneo.flows.runtime.execution_heartbeat import (
        FlowExecutionHeartbeats,
        FlowExecutionOwnershipLost,
    )

    async with sessionmanager.session() as session, session.begin():
        run, flow, repo = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        result = await repo.get_step_result(
            run_id=run.id, tenant_id=run.tenant_id, step_id=flow.steps[0].id
        )
        assert result is not None
    completed = asyncio.Event()
    resume = asyncio.Event()
    provider = AsyncMock(return_value="Late provider result")
    manager = FlowExecutionHeartbeats(max_active=1)
    # Resume publication before the paused worker's next heartbeat/probe.
    monkeypatch.setattr(manager, "start", lambda: None)

    async def invoke():
        async with manager.track(
            FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
        ):
            output = await provider()
            completed.set()
            await resume.wait()
            async with sessionmanager.session() as session, session.begin():
                repo = FlowRunRepository(session=session)
                if publication == "transcript":
                    await repo.update_input_payload(
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        input_payload_patch=FlowRunInputEnvelopePatch.transcription(
                            transcript=output
                        ),
                    )
                elif publication == "result":
                    await repo.save_step_result(
                        flow_run_id=run.id,
                        tenant_id=run.tenant_id,
                        result=result.model_copy(
                            update={
                                "status": FlowStepResultStatus.COMPLETED,
                                "output_payload_json": {"text": output},
                            }
                        ),
                        attempt_no=1,
                    )
                elif publication == "delivery":
                    await FlowRunWebhookDeliveryRepository(
                        session=session
                    ).insert_pending_delivery(
                        flow_id=flow.id,
                        tenant_id=run.tenant_id,
                        intent=WebhookDeliveryIntent(
                            flow_run_id=run.id,
                            step_id=flow.steps[0].id,
                            step_order=1,
                            attempt_no=1,
                            idempotency_key=str(uuid4()),
                            payload=WebhookPayloadRef("output"),
                        ),
                    )
                else:
                    await repo.finish_attempt(
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        step_id=flow.steps[0].id,
                        attempt_no=1,
                        status=FlowStepAttemptStatus.COMPLETED,
                        attempt_input=FlowStepAttemptInput(
                            resolved_input={"text": output}
                        ),
                    )

    async def snapshot():
        async with sessionmanager.session() as session, session.begin():
            return [
                (
                    await session.execute(
                        sa.select(table)
                        .where(
                            table.c.id == run.id
                            if table is FlowRuns.__table__
                            else table.c.flow_run_id == run.id
                        )
                        .order_by(table.c.id)
                    )
                )
                .mappings()
                .all()
                for table in (
                    FlowRuns.__table__,
                    FlowStepResults.__table__,
                    FlowStepAttempts.__table__,
                    FlowRunWebhookDeliveries.__table__,
                )
            ]

    invocation = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(completed.wait(), timeout=2)
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == run.id)
                .values(
                    execution_heartbeat_at=sa.func.clock_timestamp()
                    - timedelta(seconds=181)
                )
            )
            recovered = await _flow_run_terminalizer(
                FlowRunRepository(session=session)
            ).terminalize_stale_running_run(
                run_id=run.id,
                tenant_id=run.tenant_id,
                expected_revision=run.revision,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                    code=FlowApiErrorCode.RUN_WORKER_STALLED,
                    message="Execution heartbeat expired.",
                ),
            )
            assert recovered.did_transition
        before = await snapshot()
        resume.set()
        with pytest.raises(FlowExecutionOwnershipLost):
            await asyncio.wait_for(invocation, timeout=2)
        assert await snapshot() == before
        provider.assert_awaited_once()
    finally:
        await manager.stop()
        if not invocation.done():
            invocation.cancel()
        await asyncio.gather(invocation, return_exceptions=True)
