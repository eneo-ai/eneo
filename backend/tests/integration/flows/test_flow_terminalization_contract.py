from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationInvariantError,
    FlowRunTerminalizer,
)
from intric.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_factory import FlowFactory
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository


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
                mcp_policy="inherit",
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
                mcp_policy="inherit",
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
):
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Terminalization contract space", [model.id])
    assistant = await assistant_factory(
        session,
        "Terminalization Contract Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session, factory=FlowFactory())
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = flow.model_copy(update={"published_version": 1})
    flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_checksum="terminalization-contract",
        definition_json={
            "steps": [
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                }
                for step in flow.steps
            ]
        },
        tenant_id=admin_user.tenant_id,
    )

    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        user_id=admin_user.id,
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
    )
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
        celery_task_id="terminalization-contract",
    )
    return run, flow, run_repo


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalization_fails_run_once_and_writes_one_outbox_event(
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
            user_id=admin_user.id,
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
            celery_task_id="terminalization-contract-other-run",
        )
        terminalizer = FlowRunTerminalizer(run_repo)

        first = await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
            error_code="flow_worker_stalled",
            error_message="flow_worker_stalled: stale run reconciled.",
        )
        second = await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
            error_code="flow_worker_stalled",
            error_message="flow_worker_stalled: duplicate reconciliation.",
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
            stale_before=datetime.now(timezone.utc),
        )

    assert stale_runs == []


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
        terminalizer = FlowRunTerminalizer(run_repo)

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
    monkeypatch,
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
            "insert_terminal_audit_outbox",
            AsyncMock(side_effect=RuntimeError("outbox unavailable")),
        )
        terminalizer = FlowRunTerminalizer(run_repo)

        with pytest.raises(RuntimeError, match="outbox unavailable"):
            async with session.begin_nested():
                await terminalizer.terminalize_run(
                    run_id=run.id,
                    tenant_id=admin_user.tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.TASK_FAILURE,
                    error_code="flow_task_failure",
                    error_message="flow_task_failure: task failed.",
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
