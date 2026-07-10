from __future__ import annotations

from datetime import datetime, timedelta, timezone

from eneo.flows.runtime.flow_runtime_health import (
    FlowRuntimeHealthFlag,
    FlowRuntimeHealthPolicy,
    FlowRuntimeHealthSnapshot,
    FlowRuntimeHealthStatus,
    FlowRuntimeProbe,
    FlowRuntimeProbeFailure,
    classify_flow_runtime_health,
    flow_runtime_health_probe_failure_response,
)


def _policy() -> FlowRuntimeHealthPolicy:
    return FlowRuntimeHealthPolicy(
        stale_queued_after_seconds=30,
        stale_running_after_seconds=120,
        stale_running_unhealthy_after_seconds=240,
        review_expiry_unhealthy_after_seconds=120,
        terminal_integrity_lookback=timedelta(hours=24),
        audit_outbox_backlog_grace_seconds=300,
        webhook_outbox_backlog_grace_seconds=300,
    )


def _classify(snapshot: FlowRuntimeHealthSnapshot):
    return classify_flow_runtime_health(
        snapshot=snapshot,
        now=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        policy=_policy(),
        probe=FlowRuntimeProbe(db_query_ok=True, db_query_duration_ms=12),
    )


def test_flow_runtime_health_is_healthy_without_db_signals() -> None:
    response = _classify(FlowRuntimeHealthSnapshot())

    assert response.status == FlowRuntimeHealthStatus.HEALTHY
    assert response.status_flags == []
    assert response.probe.db_query_ok is True


def test_stale_queued_runs_degrade_health() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            queued_count=2,
            stale_queued_count=1,
            oldest_stale_queued_pending_since=datetime(
                2026, 5, 2, 11, 59, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.DEGRADED
    assert response.status_flags == [FlowRuntimeHealthFlag.STALE_QUEUED_RUNS]
    assert response.runs.oldest_stale_queued_age_seconds == 60


def test_stale_running_runs_degrade_before_reconciler_grace_expires() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            running_count=1,
            stale_running_count=1,
            oldest_stale_running_updated_at=datetime(
                2026, 5, 2, 11, 58, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.DEGRADED
    assert response.status_flags == [FlowRuntimeHealthFlag.STALE_RUNNING_RUNS]
    assert response.runs.oldest_stale_running_age_seconds == 120


def test_stale_running_runs_become_unhealthy_after_reconciler_grace_expires() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            running_count=1,
            stale_running_count=1,
            oldest_stale_running_updated_at=datetime(
                2026, 5, 2, 11, 55, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [FlowRuntimeHealthFlag.STALE_RUNNING_RECONCILER_LAG]
    assert response.runs.oldest_stale_running_age_seconds == 300


def test_expired_review_checkpoints_degrade_before_reconciler_grace_expires() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            awaiting_review_count=1,
            expired_review_checkpoint_count=1,
            oldest_expired_review_checkpoint_expires_at=datetime(
                2026, 5, 2, 11, 59, 30, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.DEGRADED
    assert response.status_flags == [FlowRuntimeHealthFlag.EXPIRED_REVIEW_CHECKPOINTS]
    assert response.review.expired_checkpoint_count == 1
    assert response.review.oldest_expired_checkpoint_age_seconds == 30


def test_expired_review_checkpoints_become_unhealthy_after_reconciler_grace_expires() -> (
    None
):
    response = _classify(
        FlowRuntimeHealthSnapshot(
            awaiting_review_count=1,
            expired_review_checkpoint_count=1,
            oldest_expired_review_checkpoint_expires_at=datetime(
                2026, 5, 2, 11, 57, 30, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [FlowRuntimeHealthFlag.REVIEW_EXPIRY_RECONCILER_LAG]
    assert response.review.expired_checkpoint_count == 1
    assert response.review.oldest_expired_checkpoint_age_seconds == 150


def test_terminal_run_open_work_is_unhealthy() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            terminal_runs_with_open_attempts_count=1,
            oldest_terminal_run_with_open_attempts_updated_at=datetime(
                2026, 5, 2, 11, 59, 30, tzinfo=timezone.utc
            ),
            terminal_runs_with_active_step_results_count=1,
            oldest_terminal_run_with_active_step_results_updated_at=datetime(
                2026, 5, 2, 11, 59, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_OPEN_ATTEMPTS,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS,
    ]
    assert (
        response.data_integrity.oldest_terminal_run_with_open_attempts_age_seconds == 30
    )
    assert (
        response.data_integrity.oldest_terminal_run_with_active_step_results_age_seconds
        == 60
    )


def test_audit_outbox_backlog_degrades_health() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            audit_outbox_pending_count=2,
            audit_outbox_delivery_backlog_count=1,
            oldest_audit_outbox_delivery_backlog_created_at=datetime(
                2026, 5, 2, 11, 50, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.DEGRADED
    assert response.status_flags == [
        FlowRuntimeHealthFlag.AUDIT_OUTBOX_DELIVERY_BACKLOG
    ]
    assert response.audit_outbox.pending_count == 2
    assert response.audit_outbox.oldest_delivery_backlog_age_seconds == 600


def test_audit_outbox_dead_letters_are_unhealthy() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            audit_outbox_dead_lettered_count=1,
            oldest_audit_outbox_dead_lettered_at=datetime(
                2026, 5, 2, 11, 57, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [FlowRuntimeHealthFlag.AUDIT_OUTBOX_DEAD_LETTERS]
    assert response.audit_outbox.dead_lettered_count == 1
    assert response.audit_outbox.oldest_dead_lettered_age_seconds == 180


def test_webhook_outbox_backlog_and_expired_claims_degrade_health() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            webhook_outbox_pending_count=2,
            webhook_outbox_delivery_backlog_count=1,
            oldest_webhook_outbox_delivery_backlog_created_at=datetime(
                2026, 5, 2, 11, 50, tzinfo=timezone.utc
            ),
            webhook_outbox_expired_claim_count=1,
            oldest_webhook_outbox_expired_claim_expires_at=datetime(
                2026, 5, 2, 11, 58, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.DEGRADED
    assert response.status_flags == [
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DELIVERY_BACKLOG,
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_EXPIRED_CLAIMS,
    ]
    assert response.webhook_outbox.pending_count == 2
    assert response.webhook_outbox.delivery_backlog_count == 1
    assert response.webhook_outbox.expired_claim_count == 1
    assert response.webhook_outbox.oldest_delivery_backlog_age_seconds == 600
    assert response.webhook_outbox.oldest_expired_claim_age_seconds == 120


def test_webhook_outbox_dead_letters_are_unhealthy() -> None:
    response = _classify(
        FlowRuntimeHealthSnapshot(
            webhook_outbox_dead_lettered_count=1,
            oldest_webhook_outbox_dead_lettered_at=datetime(
                2026, 5, 2, 11, 57, tzinfo=timezone.utc
            ),
        )
    )

    assert response.status == FlowRuntimeHealthStatus.UNHEALTHY
    assert response.status_flags == [FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DEAD_LETTERS]
    assert response.webhook_outbox.dead_lettered_count == 1
    assert response.webhook_outbox.oldest_dead_lettered_age_seconds == 180


def test_db_probe_failure_makes_health_unknown() -> None:
    response = flow_runtime_health_probe_failure_response(
        now=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        policy=_policy(),
        query_duration_ms=2000,
        failure=FlowRuntimeProbeFailure.TIMEOUT,
    )

    assert response.status == FlowRuntimeHealthStatus.UNKNOWN
    assert response.status_flags == []
    assert response.probe.db_query_ok is False
    assert response.probe.db_query_failure == FlowRuntimeProbeFailure.TIMEOUT
