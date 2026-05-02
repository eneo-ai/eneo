from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.flow_tables import FlowRuns
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.enums import FlowRunStatus
from intric.flows.flow_factory import FlowFactory
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.runtime.flow_runtime_health import (
    FlowRuntimeHealthFlag,
    FlowRuntimeHealthPolicy,
    FlowRuntimeHealthStatus,
    FlowRuntimeProbe,
    classify_flow_runtime_health,
    load_flow_runtime_health_snapshot,
)


def _policy() -> FlowRuntimeHealthPolicy:
    return FlowRuntimeHealthPolicy(
        stale_queued_after_seconds=30,
        stale_running_after_seconds=60,
        stale_running_unhealthy_after_seconds=120,
        terminal_integrity_lookback=timedelta(hours=24),
    )


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
        name="Runtime Health Flow",
        description="Flow used for runtime health tests.",
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
            )
        ],
    )


async def _create_published_flow(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> Flow:
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Flow runtime health space", [model.id])
    assistant = await assistant_factory(
        session,
        "Flow Runtime Health Assistant",
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
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_checksum="runtime-health",
        definition_json={
            "steps": [
                {
                    "step_id": str(flow.steps[0].id),
                    "assistant_id": str(flow.steps[0].assistant_id),
                    "step_order": 1,
                }
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    return flow


async def _create_run(
    *,
    run_repo: FlowRunRepository,
    flow: Flow,
    admin_user,
    case: str,
):
    return await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"case": case},
        preseed_steps=[
            {
                "step_id": flow.steps[0].id,
                "assistant_id": flow.steps[0].assistant_id,
                "step_order": 1,
            }
        ],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_health_endpoint_returns_db_only_probe(client):
    response = await client.get("/api/healthz/flows")

    assert response.status_code == 200
    payload = response.json()
    assert payload["probe"]["scope"] == "db_only"
    assert "tenant_id" not in payload
    assert "flow_id" not in payload
    assert "run_id" not in payload


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_health_snapshot_is_healthy_without_runs(db_container):
    async with db_container() as container:
        session = container.session()
        policy = _policy()
        now = datetime.now(timezone.utc)

        snapshot = await load_flow_runtime_health_snapshot(
            session=session,
            now=now,
            policy=policy,
        )
        response = classify_flow_runtime_health(
            snapshot=snapshot,
            now=now,
            policy=policy,
            probe=FlowRuntimeProbe(db_query_ok=True, db_query_duration_ms=1),
        )

    assert response.status == FlowRuntimeHealthStatus.HEALTHY
    assert response.runs.queued_count == 0
    assert response.status_flags == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_health_snapshot_reports_stale_runs_and_open_terminal_work(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        flow = await _create_published_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        policy = _policy()
        now = datetime.now(timezone.utc)

        stale_queued = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="stale-queued",
        )
        stale_running = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="stale-running",
        )
        awaiting_review = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="awaiting-review",
        )
        terminal_with_open_attempt = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="terminal-open-attempt",
        )

        assert await run_repo.mark_running_if_claimable(
            run_id=stale_running.id,
            tenant_id=admin_user.tenant_id,
        )
        assert await run_repo.mark_running_if_claimable(
            run_id=terminal_with_open_attempt.id,
            tenant_id=admin_user.tenant_id,
        )
        claimed = await run_repo.claim_step_result(
            run_id=terminal_with_open_attempt.id,
            step_id=flow.steps[0].id,
            tenant_id=admin_user.tenant_id,
        )
        assert claimed is not None
        await run_repo.create_or_get_attempt_started(
            run_id=terminal_with_open_attempt.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=1,
            celery_task_id="runtime-health",
        )

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == stale_queued.id)
            .values(
                updated_at=now
                - timedelta(seconds=policy.stale_queued_after_seconds + 5)
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == stale_running.id)
            .values(
                status=FlowRunStatus.RUNNING.value,
                updated_at=now
                - timedelta(seconds=policy.stale_running_unhealthy_after_seconds + 5),
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == awaiting_review.id)
            .values(status=FlowRunStatus.AWAITING_REVIEW.value)
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == terminal_with_open_attempt.id)
            .values(
                status=FlowRunStatus.COMPLETED.value,
                updated_at=now - timedelta(minutes=5),
            )
        )
        await session.flush()

        snapshot = await load_flow_runtime_health_snapshot(
            session=session,
            now=now,
            policy=policy,
        )
        response = classify_flow_runtime_health(
            snapshot=snapshot,
            now=now,
            policy=policy,
            probe=FlowRuntimeProbe(db_query_ok=True, db_query_duration_ms=8),
        )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.runs.queued_count == 1
    assert response.runs.running_count == 1
    assert response.runs.awaiting_review_count == 1
    assert response.runs.stale_queued_count == 1
    assert response.runs.stale_running_count == 1
    assert response.status_flags == [
        FlowRuntimeHealthFlag.STALE_QUEUED_RUNS,
        FlowRuntimeHealthFlag.STALE_RUNNING_RECONCILER_LAG,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_OPEN_ATTEMPTS,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS,
    ]
    assert response.data_integrity.terminal_runs_with_open_attempts_count == 1
    assert response.data_integrity.terminal_runs_with_active_step_results_count == 1
