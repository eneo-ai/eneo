from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunWebhookDeliveries,
)
from eneo.flows.application.flow_run_audit_outbox_delivery import (
    FlowRunAuditOutboxDeliveryService,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import FlowRunStatus
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.runtime.flow_runtime_health import (
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
        review_expiry_unhealthy_after_seconds=120,
        terminal_integrity_lookback=timedelta(hours=24),
        audit_outbox_backlog_grace_seconds=300,
        webhook_outbox_backlog_grace_seconds=300,
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
                    "step_id": str(flow.steps[0].id),
                    "assistant_id": str(flow.steps[0].assistant_id),
                    "step_order": 1,
                }
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
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
        principal_user_id=admin_user.id,
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


async def _create_webhook_delivery_attempt(
    *,
    run_repo: FlowRunRepository,
    flow: Flow,
    admin_user,
    case: str,
):
    run = await _create_run(
        run_repo=run_repo,
        flow=flow,
        admin_user=admin_user,
        case=case,
    )
    await run_repo.create_or_get_attempt_started(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        step_id=flow.steps[0].id,
        step_order=1,
        attempt_no=1,
        celery_task_id=f"runtime-health-webhook-{case}",
    )
    return run


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
        run_repo = FlowRunRepository(session=session)
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
            expected_revision=stale_running.revision,
        )
        assert await run_repo.mark_running_if_claimable(
            run_id=terminal_with_open_attempt.id,
            tenant_id=admin_user.tenant_id,
            expected_revision=terminal_with_open_attempt.revision,
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
                dispatch_pending_since=now
                - timedelta(seconds=policy.stale_queued_after_seconds + 5),
                dispatched_at=None,
                dispatch_last_error=None,
                dispatch_exhausted_at=now - timedelta(minutes=1),
                updated_at=now,
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
        await run_repo.create_or_get_attempt_started(
            run_id=awaiting_review.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=flow.steps[0].id,
            step_order=1,
            attempt_no=1,
            celery_task_id="runtime-health-review",
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == awaiting_review.id)
            .values(status=FlowRunStatus.AWAITING_REVIEW.value)
        )
        await session.execute(
            sa.insert(FlowRunReviewCheckpoints).values(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=awaiting_review.id,
                step_id=flow.steps[0].id,
                step_order=1,
                attempt_no=1,
                state="awaiting_review",
                revision=1,
                schema_version=1,
                original_payload_json={"text": "Needs review"},
                current_payload_json={"text": "Needs review"},
                review_mode="view",
                output_type="text",
                requester_user_id=admin_user.id,
                requester_principal_type="user",
                next_step_ids_json=[],
                expires_at=now
                - timedelta(seconds=policy.review_expiry_unhealthy_after_seconds + 5),
            )
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
    assert response.runs.oldest_stale_queued_age_seconds == (
        policy.stale_queued_after_seconds + 5
    )
    assert response.runs.stale_running_count == 1
    assert response.runs.accepted_dispatch_exhausted_count == 1
    assert response.runs.oldest_accepted_dispatch_exhausted_age_seconds == 60
    assert response.status_flags == [
        FlowRuntimeHealthFlag.STALE_QUEUED_RUNS,
        FlowRuntimeHealthFlag.ACCEPTED_DISPATCH_EXHAUSTED,
        FlowRuntimeHealthFlag.STALE_RUNNING_RECONCILER_LAG,
        FlowRuntimeHealthFlag.REVIEW_EXPIRY_RECONCILER_LAG,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_OPEN_ATTEMPTS,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS,
    ]
    assert response.review.expired_checkpoint_count == 1
    assert response.review.oldest_expired_checkpoint_age_seconds == 125
    assert response.data_integrity.terminal_runs_with_open_attempts_count == 1
    assert response.data_integrity.terminal_runs_with_active_step_results_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_health_snapshot_reports_audit_outbox_delivery_state(
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
        run_repo = FlowRunRepository(session=session)
        policy = _policy()
        now = datetime.now(timezone.utc)
        pending_run = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="pending-audit-outbox",
        )
        dead_lettered_run = await _create_run(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="dead-lettered-audit-outbox",
        )
        pending_outbox_id = uuid4()
        dead_lettered_outbox_id = uuid4()
        dead_lettered_at = now - timedelta(minutes=2)
        await session.execute(
            sa.insert(FlowRunAuditOutbox).values(
                id=pending_outbox_id,
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=pending_run.id,
                run_revision=pending_run.revision,
                description="flow_run_completed:executor_completed",
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=pending_run.id,
                actor_id=admin_user.id,
                actor_type="user",
                source="executor_completed",
                target_status="completed",
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=now
                - timedelta(seconds=policy.audit_outbox_backlog_grace_seconds + 5),
                created_at=now - timedelta(minutes=10),
            )
        )
        await session.execute(
            sa.insert(FlowRunAuditOutbox).values(
                id=dead_lettered_outbox_id,
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=dead_lettered_run.id,
                run_revision=dead_lettered_run.revision,
                description="flow_run_failed:task_failure",
                action="flow_run_failed",
                entity_type="flow_run",
                entity_id=dead_lettered_run.id,
                actor_id=admin_user.id,
                actor_type="user",
                source="task_failure",
                target_status="failed",
                error_code="flow_task_failure",
                error_message="flow_task_failure: task failed.",
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error="ValueError: invalid audit row",
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

        delivery_service = FlowRunAuditOutboxDeliveryService(
            audit_outbox_repo=FlowRunAuditOutboxRepository(session=session),
            audit_log_repo=AuditLogRepositoryImpl(session),
        )
        await delivery_service.redrive_dead_lettered(
            outbox_id=dead_lettered_outbox_id,
            expected_dead_lettered_at=dead_lettered_at,
            reason="Audit storage recovered.",
            now=now,
        )
        delivery_result = await delivery_service.deliver_due(now=now)
        recovered_snapshot = await load_flow_runtime_health_snapshot(
            session=session,
            now=now,
            policy=policy,
        )
        recovered_response = classify_flow_runtime_health(
            snapshot=recovered_snapshot,
            now=now,
            policy=policy,
            probe=FlowRuntimeProbe(db_query_ok=True, db_query_duration_ms=8),
        )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [
        FlowRuntimeHealthFlag.AUDIT_OUTBOX_DELIVERY_BACKLOG,
        FlowRuntimeHealthFlag.AUDIT_OUTBOX_DEAD_LETTERS,
    ]
    assert response.audit_outbox.pending_count == 1
    assert response.audit_outbox.delivery_backlog_count == 1
    assert response.audit_outbox.dead_lettered_count == 1
    assert response.audit_outbox.oldest_delivery_backlog_age_seconds == 600
    assert response.audit_outbox.oldest_dead_lettered_age_seconds == 120
    assert delivery_result.delivered_count == 2
    assert recovered_response.status == FlowRuntimeHealthStatus.HEALTHY
    assert recovered_response.audit_outbox.pending_count == 0
    assert recovered_response.audit_outbox.dead_lettered_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_runtime_health_snapshot_reports_webhook_outbox_delivery_state(
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
        run_repo = FlowRunRepository(session=session)
        policy = _policy()
        now = datetime.now(timezone.utc)
        pending_run = await _create_webhook_delivery_attempt(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="pending-webhook-outbox",
        )
        expired_claim_run = await _create_webhook_delivery_attempt(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="expired-claim-webhook-outbox",
        )
        dead_lettered_run = await _create_webhook_delivery_attempt(
            run_repo=run_repo,
            flow=flow,
            admin_user=admin_user,
            case="dead-lettered-webhook-outbox",
        )
        await session.execute(
            sa.insert(FlowRunWebhookDeliveries).values(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=pending_run.id,
                step_id=flow.steps[0].id,
                step_order=1,
                attempt_no=1,
                idempotency_key=f"webhook-pending-{uuid4()}",
                payload_ref="runtime-health-webhook-pending",
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=now
                - timedelta(seconds=policy.webhook_outbox_backlog_grace_seconds + 5),
                created_at=now - timedelta(minutes=10),
            )
        )
        await session.execute(
            sa.insert(FlowRunWebhookDeliveries).values(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=expired_claim_run.id,
                step_id=flow.steps[0].id,
                step_order=1,
                attempt_no=1,
                idempotency_key=f"webhook-expired-claim-{uuid4()}",
                payload_ref="runtime-health-webhook-expired-claim",
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=1,
                next_delivery_at=now,
                claim_token=uuid4(),
                claimed_at=now - timedelta(minutes=10),
                claim_expires_at=now - timedelta(minutes=2),
                created_at=now - timedelta(minutes=9),
            )
        )
        await session.execute(
            sa.insert(FlowRunWebhookDeliveries).values(
                tenant_id=admin_user.tenant_id,
                flow_id=flow.id,
                flow_run_id=dead_lettered_run.id,
                step_id=flow.steps[0].id,
                step_order=1,
                attempt_no=1,
                idempotency_key=f"webhook-dead-lettered-{uuid4()}",
                payload_ref="runtime-health-webhook-dead-lettered",
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=now - timedelta(minutes=3),
                delivery_last_error="RuntimeError: webhook failed",
                created_at=now - timedelta(minutes=8),
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
    assert response.status_flags == [
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DELIVERY_BACKLOG,
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_EXPIRED_CLAIMS,
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DEAD_LETTERS,
    ]
    assert response.webhook_outbox.pending_count == 2
    assert response.webhook_outbox.delivery_backlog_count == 1
    assert response.webhook_outbox.expired_claim_count == 1
    assert response.webhook_outbox.dead_lettered_count == 1
    assert response.webhook_outbox.oldest_delivery_backlog_age_seconds == 600
    assert response.webhook_outbox.oldest_expired_claim_age_seconds == 120
    assert response.webhook_outbox.oldest_dead_lettered_age_seconds == 180
