from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunWebhookDeliveries,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_BACKLOG_GRACE_SECONDS,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    flow_stale_running_reconcile_after_seconds,
    flow_stale_running_unhealthy_after_seconds,
)
from eneo.flows.enums import (
    ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES,
    OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES,
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    TERMINAL_FLOW_RUN_STATUS_VALUES,
    FlowRunStatus,
)
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_UNHEALTHY_AFTER_SECONDS,
)

TERMINAL_INTEGRITY_LOOKBACK_HOURS = 24


class FlowRuntimeHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class FlowRuntimeHealthFlag(str, Enum):
    STALE_QUEUED_RUNS = "STALE_QUEUED_RUNS"
    ACCEPTED_DISPATCH_EXHAUSTED = "ACCEPTED_DISPATCH_EXHAUSTED"
    STALE_RUNNING_RUNS = "STALE_RUNNING_RUNS"
    STALE_RUNNING_RECONCILER_LAG = "STALE_RUNNING_RECONCILER_LAG"
    EXPIRED_REVIEW_CHECKPOINTS = "EXPIRED_REVIEW_CHECKPOINTS"
    REVIEW_EXPIRY_RECONCILER_LAG = "REVIEW_EXPIRY_RECONCILER_LAG"
    TERMINAL_RUNS_WITH_OPEN_ATTEMPTS = "TERMINAL_RUNS_WITH_OPEN_ATTEMPTS"
    TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS = "TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS"
    AUDIT_OUTBOX_DELIVERY_BACKLOG = "AUDIT_OUTBOX_DELIVERY_BACKLOG"
    AUDIT_OUTBOX_DEAD_LETTERS = "AUDIT_OUTBOX_DEAD_LETTERS"
    WEBHOOK_OUTBOX_DELIVERY_BACKLOG = "WEBHOOK_OUTBOX_DELIVERY_BACKLOG"
    WEBHOOK_OUTBOX_EXPIRED_CLAIMS = "WEBHOOK_OUTBOX_EXPIRED_CLAIMS"
    WEBHOOK_OUTBOX_DEAD_LETTERS = "WEBHOOK_OUTBOX_DEAD_LETTERS"


class FlowRuntimeProbeFailure(str, Enum):
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FlowRuntimeHealthPolicy:
    stale_queued_after_seconds: int
    stale_running_after_seconds: int
    stale_running_unhealthy_after_seconds: int
    review_expiry_unhealthy_after_seconds: int
    terminal_integrity_lookback: timedelta
    audit_outbox_backlog_grace_seconds: int
    webhook_outbox_backlog_grace_seconds: int


@dataclass(frozen=True, slots=True)
class FlowRuntimeHealthSnapshot:
    queued_count: int = 0
    running_count: int = 0
    awaiting_review_count: int = 0
    stale_queued_count: int = 0
    stale_running_count: int = 0
    oldest_stale_queued_pending_since: datetime | None = None
    oldest_stale_running_updated_at: datetime | None = None
    accepted_dispatch_exhausted_count: int = 0
    oldest_accepted_dispatch_exhausted_at: datetime | None = None
    expired_review_checkpoint_count: int = 0
    oldest_expired_review_checkpoint_expires_at: datetime | None = None
    terminal_runs_with_open_attempts_count: int = 0
    oldest_terminal_run_with_open_attempts_updated_at: datetime | None = None
    terminal_runs_with_active_step_results_count: int = 0
    oldest_terminal_run_with_active_step_results_updated_at: datetime | None = None
    audit_outbox_pending_count: int = 0
    audit_outbox_delivery_backlog_count: int = 0
    oldest_audit_outbox_delivery_backlog_created_at: datetime | None = None
    audit_outbox_dead_lettered_count: int = 0
    oldest_audit_outbox_dead_lettered_at: datetime | None = None
    webhook_outbox_pending_count: int = 0
    webhook_outbox_delivery_backlog_count: int = 0
    oldest_webhook_outbox_delivery_backlog_created_at: datetime | None = None
    webhook_outbox_expired_claim_count: int = 0
    oldest_webhook_outbox_expired_claim_expires_at: datetime | None = None
    webhook_outbox_dead_lettered_count: int = 0
    oldest_webhook_outbox_dead_lettered_at: datetime | None = None


class FlowRuntimeProbe(BaseModel):
    scope: str = "db_only"
    db_query_ok: bool
    db_query_duration_ms: int | None = None
    db_query_failure: FlowRuntimeProbeFailure | None = None


class FlowRuntimeRunSummary(BaseModel):
    queued_count: int = 0
    running_count: int = 0
    awaiting_review_count: int = 0
    stale_queued_count: int = 0
    stale_running_count: int = 0
    oldest_stale_queued_age_seconds: int | None = None
    oldest_stale_running_age_seconds: int | None = None
    accepted_dispatch_exhausted_count: int = Field(
        default=0,
        description=(
            "Queued runs whose bounded dispatch epoch is exhausted and whose latest "
            "delivery was broker-accepted or has no durable rejection receipt. Any "
            "positive count makes Flow runtime health UNHEALTHY; inspect broker and "
            "worker health, then use the run redispatch endpoint with the observed "
            "dispatch-exhaustion timestamp when no delayed delivery claims the run."
        ),
    )
    oldest_accepted_dispatch_exhausted_age_seconds: int | None = Field(
        default=None,
        description=(
            "Whole seconds since the oldest matching run's dispatch_exhausted_at; "
            "null when accepted-or-outcome-unknown dispatch exhaustion is absent."
        ),
    )


class FlowRuntimeReviewSummary(BaseModel):
    expired_checkpoint_count: int = 0
    oldest_expired_checkpoint_age_seconds: int | None = None


class FlowRuntimeDataIntegrity(BaseModel):
    terminal_runs_with_open_attempts_count: int = 0
    oldest_terminal_run_with_open_attempts_age_seconds: int | None = None
    terminal_runs_with_active_step_results_count: int = 0
    oldest_terminal_run_with_active_step_results_age_seconds: int | None = None


class FlowRuntimeAuditOutboxSummary(BaseModel):
    pending_count: int = 0
    delivery_backlog_count: int = 0
    dead_lettered_count: int = 0
    oldest_delivery_backlog_age_seconds: int | None = None
    oldest_dead_lettered_age_seconds: int | None = None


class FlowRuntimeWebhookOutboxSummary(BaseModel):
    pending_count: int = 0
    delivery_backlog_count: int = 0
    expired_claim_count: int = 0
    dead_lettered_count: int = 0
    oldest_delivery_backlog_age_seconds: int | None = None
    oldest_expired_claim_age_seconds: int | None = None
    oldest_dead_lettered_age_seconds: int | None = None


class FlowRuntimeHealthThresholds(BaseModel):
    stale_queued_after_seconds: int
    stale_running_after_seconds: int
    stale_running_unhealthy_after_seconds: int
    review_expiry_unhealthy_after_seconds: int
    terminal_integrity_lookback_hours: int
    audit_outbox_backlog_grace_seconds: int
    webhook_outbox_backlog_grace_seconds: int


class FlowRuntimeHealthResponse(BaseModel):
    status: FlowRuntimeHealthStatus
    status_flags: list[FlowRuntimeHealthFlag] = Field(
        default_factory=list[FlowRuntimeHealthFlag]
    )
    status_reason: str
    response_timestamp_utc: datetime
    probe: FlowRuntimeProbe
    runs: FlowRuntimeRunSummary = Field(default_factory=FlowRuntimeRunSummary)
    review: FlowRuntimeReviewSummary = Field(default_factory=FlowRuntimeReviewSummary)
    data_integrity: FlowRuntimeDataIntegrity = Field(
        default_factory=FlowRuntimeDataIntegrity
    )
    audit_outbox: FlowRuntimeAuditOutboxSummary = Field(
        default_factory=FlowRuntimeAuditOutboxSummary
    )
    webhook_outbox: FlowRuntimeWebhookOutboxSummary = Field(
        default_factory=FlowRuntimeWebhookOutboxSummary
    )
    thresholds: FlowRuntimeHealthThresholds


def build_flow_runtime_health_policy(
    *, task_timeout_seconds: int
) -> FlowRuntimeHealthPolicy:
    return FlowRuntimeHealthPolicy(
        stale_queued_after_seconds=FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
        stale_running_after_seconds=flow_stale_running_reconcile_after_seconds(
            task_timeout_seconds=task_timeout_seconds
        ),
        stale_running_unhealthy_after_seconds=flow_stale_running_unhealthy_after_seconds(
            task_timeout_seconds=task_timeout_seconds
        ),
        review_expiry_unhealthy_after_seconds=(
            FLOW_REVIEW_EXPIRY_UNHEALTHY_AFTER_SECONDS
        ),
        terminal_integrity_lookback=timedelta(hours=TERMINAL_INTEGRITY_LOOKBACK_HOURS),
        audit_outbox_backlog_grace_seconds=FLOW_AUDIT_OUTBOX_BACKLOG_GRACE_SECONDS,
        webhook_outbox_backlog_grace_seconds=FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
    )


async def load_flow_runtime_health_snapshot(
    *,
    session: AsyncSession,
    now: datetime,
    policy: FlowRuntimeHealthPolicy,
) -> FlowRuntimeHealthSnapshot:
    stale_queued_before = now - timedelta(seconds=policy.stale_queued_after_seconds)
    stale_running_before = now - timedelta(seconds=policy.stale_running_after_seconds)
    terminal_integrity_after = now - policy.terminal_integrity_lookback
    audit_outbox_backlog_before = now - timedelta(
        seconds=policy.audit_outbox_backlog_grace_seconds
    )
    webhook_outbox_backlog_before = now - timedelta(
        seconds=policy.webhook_outbox_backlog_grace_seconds
    )

    status_counts = await _load_run_status_counts(session)
    stale_queued = await _load_stale_run_summary(
        session=session,
        status=FlowRunStatus.QUEUED,
        stale_before=stale_queued_before,
    )
    stale_running = await _load_stale_run_summary(
        session=session,
        status=FlowRunStatus.RUNNING,
        stale_before=stale_running_before,
    )
    accepted_dispatch_exhausted = await _load_accepted_dispatch_exhausted_summary(
        session=session
    )
    expired_review_checkpoints = await _load_expired_review_checkpoint_summary(
        session=session,
        expires_before=now,
    )
    terminal_open_attempts = await _load_terminal_runs_with_open_attempts_summary(
        session=session,
        updated_after=terminal_integrity_after,
    )
    terminal_active_step_results = (
        await _load_terminal_runs_with_active_step_results_summary(
            session=session,
            updated_after=terminal_integrity_after,
        )
    )
    audit_outbox = await _load_audit_outbox_summary(
        session=session,
        backlog_before=audit_outbox_backlog_before,
    )
    webhook_outbox = await _load_webhook_outbox_summary(
        session=session,
        backlog_before=webhook_outbox_backlog_before,
        now=now,
    )

    return FlowRuntimeHealthSnapshot(
        queued_count=status_counts.get(FlowRunStatus.QUEUED.value, 0),
        running_count=status_counts.get(FlowRunStatus.RUNNING.value, 0),
        awaiting_review_count=status_counts.get(FlowRunStatus.AWAITING_REVIEW.value, 0),
        stale_queued_count=stale_queued.count,
        stale_running_count=stale_running.count,
        oldest_stale_queued_pending_since=stale_queued.oldest_anchor_at,
        oldest_stale_running_updated_at=stale_running.oldest_anchor_at,
        accepted_dispatch_exhausted_count=accepted_dispatch_exhausted.count,
        oldest_accepted_dispatch_exhausted_at=(
            accepted_dispatch_exhausted.oldest_anchor_at
        ),
        expired_review_checkpoint_count=expired_review_checkpoints.count,
        oldest_expired_review_checkpoint_expires_at=(
            expired_review_checkpoints.oldest_expires_at
        ),
        terminal_runs_with_open_attempts_count=terminal_open_attempts.count,
        oldest_terminal_run_with_open_attempts_updated_at=(
            terminal_open_attempts.oldest_anchor_at
        ),
        terminal_runs_with_active_step_results_count=(
            terminal_active_step_results.count
        ),
        oldest_terminal_run_with_active_step_results_updated_at=(
            terminal_active_step_results.oldest_anchor_at
        ),
        audit_outbox_pending_count=audit_outbox.pending_count,
        audit_outbox_delivery_backlog_count=audit_outbox.delivery_backlog_count,
        oldest_audit_outbox_delivery_backlog_created_at=(
            audit_outbox.oldest_backlog_created_at
        ),
        audit_outbox_dead_lettered_count=audit_outbox.dead_lettered_count,
        oldest_audit_outbox_dead_lettered_at=(audit_outbox.oldest_dead_lettered_at),
        webhook_outbox_pending_count=webhook_outbox.pending_count,
        webhook_outbox_delivery_backlog_count=webhook_outbox.delivery_backlog_count,
        oldest_webhook_outbox_delivery_backlog_created_at=(
            webhook_outbox.oldest_backlog_created_at
        ),
        webhook_outbox_expired_claim_count=webhook_outbox.expired_claim_count,
        oldest_webhook_outbox_expired_claim_expires_at=(
            webhook_outbox.oldest_expired_claim_expires_at
        ),
        webhook_outbox_dead_lettered_count=webhook_outbox.dead_lettered_count,
        oldest_webhook_outbox_dead_lettered_at=(webhook_outbox.oldest_dead_lettered_at),
    )


def classify_flow_runtime_health(
    *,
    snapshot: FlowRuntimeHealthSnapshot,
    now: datetime,
    policy: FlowRuntimeHealthPolicy,
    probe: FlowRuntimeProbe,
) -> FlowRuntimeHealthResponse:
    stale_queued_age = _age_seconds(now, snapshot.oldest_stale_queued_pending_since)
    stale_running_age = _age_seconds(now, snapshot.oldest_stale_running_updated_at)
    accepted_dispatch_exhausted_age = _age_seconds(
        now, snapshot.oldest_accepted_dispatch_exhausted_at
    )
    expired_review_checkpoint_age = _age_seconds(
        now,
        snapshot.oldest_expired_review_checkpoint_expires_at,
    )
    open_attempt_age = _age_seconds(
        now, snapshot.oldest_terminal_run_with_open_attempts_updated_at
    )
    active_step_result_age = _age_seconds(
        now,
        snapshot.oldest_terminal_run_with_active_step_results_updated_at,
    )
    audit_backlog_age = _age_seconds(
        now,
        snapshot.oldest_audit_outbox_delivery_backlog_created_at,
    )
    audit_dead_letter_age = _age_seconds(
        now,
        snapshot.oldest_audit_outbox_dead_lettered_at,
    )
    webhook_backlog_age = _age_seconds(
        now,
        snapshot.oldest_webhook_outbox_delivery_backlog_created_at,
    )
    webhook_expired_claim_age = _age_seconds(
        now,
        snapshot.oldest_webhook_outbox_expired_claim_expires_at,
    )
    webhook_dead_letter_age = _age_seconds(
        now,
        snapshot.oldest_webhook_outbox_dead_lettered_at,
    )
    status_flags = _flow_runtime_health_flags(
        snapshot=snapshot,
        stale_running_age_seconds=stale_running_age,
        expired_review_checkpoint_age_seconds=expired_review_checkpoint_age,
        policy=policy,
    )
    status = _flow_runtime_health_status(
        probe=probe,
        status_flags=status_flags,
    )

    return FlowRuntimeHealthResponse(
        status=status,
        status_flags=status_flags,
        status_reason=_flow_runtime_status_reason(status=status),
        response_timestamp_utc=now,
        probe=probe,
        runs=FlowRuntimeRunSummary(
            queued_count=snapshot.queued_count,
            running_count=snapshot.running_count,
            awaiting_review_count=snapshot.awaiting_review_count,
            stale_queued_count=snapshot.stale_queued_count,
            stale_running_count=snapshot.stale_running_count,
            oldest_stale_queued_age_seconds=stale_queued_age,
            oldest_stale_running_age_seconds=stale_running_age,
            accepted_dispatch_exhausted_count=(
                snapshot.accepted_dispatch_exhausted_count
            ),
            oldest_accepted_dispatch_exhausted_age_seconds=(
                accepted_dispatch_exhausted_age
            ),
        ),
        review=FlowRuntimeReviewSummary(
            expired_checkpoint_count=snapshot.expired_review_checkpoint_count,
            oldest_expired_checkpoint_age_seconds=expired_review_checkpoint_age,
        ),
        data_integrity=FlowRuntimeDataIntegrity(
            terminal_runs_with_open_attempts_count=(
                snapshot.terminal_runs_with_open_attempts_count
            ),
            oldest_terminal_run_with_open_attempts_age_seconds=open_attempt_age,
            terminal_runs_with_active_step_results_count=(
                snapshot.terminal_runs_with_active_step_results_count
            ),
            oldest_terminal_run_with_active_step_results_age_seconds=(
                active_step_result_age
            ),
        ),
        audit_outbox=FlowRuntimeAuditOutboxSummary(
            pending_count=snapshot.audit_outbox_pending_count,
            delivery_backlog_count=snapshot.audit_outbox_delivery_backlog_count,
            dead_lettered_count=snapshot.audit_outbox_dead_lettered_count,
            oldest_delivery_backlog_age_seconds=audit_backlog_age,
            oldest_dead_lettered_age_seconds=audit_dead_letter_age,
        ),
        webhook_outbox=FlowRuntimeWebhookOutboxSummary(
            pending_count=snapshot.webhook_outbox_pending_count,
            delivery_backlog_count=snapshot.webhook_outbox_delivery_backlog_count,
            expired_claim_count=snapshot.webhook_outbox_expired_claim_count,
            dead_lettered_count=snapshot.webhook_outbox_dead_lettered_count,
            oldest_delivery_backlog_age_seconds=webhook_backlog_age,
            oldest_expired_claim_age_seconds=webhook_expired_claim_age,
            oldest_dead_lettered_age_seconds=webhook_dead_letter_age,
        ),
        thresholds=FlowRuntimeHealthThresholds(
            stale_queued_after_seconds=policy.stale_queued_after_seconds,
            stale_running_after_seconds=policy.stale_running_after_seconds,
            stale_running_unhealthy_after_seconds=(
                policy.stale_running_unhealthy_after_seconds
            ),
            review_expiry_unhealthy_after_seconds=(
                policy.review_expiry_unhealthy_after_seconds
            ),
            terminal_integrity_lookback_hours=TERMINAL_INTEGRITY_LOOKBACK_HOURS,
            audit_outbox_backlog_grace_seconds=(
                policy.audit_outbox_backlog_grace_seconds
            ),
            webhook_outbox_backlog_grace_seconds=(
                policy.webhook_outbox_backlog_grace_seconds
            ),
        ),
    )


def flow_runtime_health_probe_failure_response(
    *,
    now: datetime,
    policy: FlowRuntimeHealthPolicy,
    query_duration_ms: int | None,
    failure: FlowRuntimeProbeFailure,
) -> FlowRuntimeHealthResponse:
    return classify_flow_runtime_health(
        snapshot=FlowRuntimeHealthSnapshot(),
        now=now,
        policy=policy,
        probe=FlowRuntimeProbe(
            db_query_ok=False,
            db_query_duration_ms=query_duration_ms,
            db_query_failure=failure,
        ),
    )


@dataclass(frozen=True, slots=True)
class _RunSummary:
    count: int
    oldest_anchor_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ReviewCheckpointExpirySummary:
    count: int
    oldest_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class _AuditOutboxSummary:
    pending_count: int
    delivery_backlog_count: int
    oldest_backlog_created_at: datetime | None
    dead_lettered_count: int
    oldest_dead_lettered_at: datetime | None


@dataclass(frozen=True, slots=True)
class _WebhookOutboxSummary:
    pending_count: int
    delivery_backlog_count: int
    oldest_backlog_created_at: datetime | None
    expired_claim_count: int
    oldest_expired_claim_expires_at: datetime | None
    dead_lettered_count: int
    oldest_dead_lettered_at: datetime | None


async def _load_run_status_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            sa.select(FlowRuns.status, sa.func.count())
            .select_from(FlowRuns)
            .where(
                FlowRuns.status.in_(
                    (
                        FlowRunStatus.QUEUED.value,
                        FlowRunStatus.RUNNING.value,
                        FlowRunStatus.AWAITING_REVIEW.value,
                    )
                )
            )
            .group_by(FlowRuns.status)
        )
    ).all()
    return {str(status): int(count or 0) for status, count in rows}


async def _load_stale_run_summary(
    *,
    session: AsyncSession,
    status: FlowRunStatus,
    stale_before: datetime,
) -> _RunSummary:
    age_anchor = (
        FlowRuns.dispatch_pending_since
        if status == FlowRunStatus.QUEUED
        else FlowRuns.updated_at
    )
    count, oldest_anchor_at = (
        await session.execute(
            sa.select(sa.func.count(), sa.func.min(age_anchor))
            .select_from(FlowRuns)
            .where(FlowRuns.status == status.value)
            .where(age_anchor <= stale_before)
        )
    ).one()
    return _RunSummary(
        count=int(count or 0),
        oldest_anchor_at=_normalize_datetime(oldest_anchor_at),
    )


async def _load_accepted_dispatch_exhausted_summary(
    *, session: AsyncSession
) -> _RunSummary:
    count, oldest_exhausted_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRuns.dispatch_exhausted_at),
            )
            .select_from(FlowRuns)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(
                sa.or_(
                    FlowRuns.dispatched_at.is_not(None),
                    FlowRuns.dispatch_last_error.is_(None),
                )
            )
            .where(FlowRuns.dispatch_exhausted_at.is_not(None))
        )
    ).one()
    return _RunSummary(
        count=int(count or 0),
        oldest_anchor_at=_normalize_datetime(oldest_exhausted_at),
    )


async def _load_terminal_runs_with_open_attempts_summary(
    *,
    session: AsyncSession,
    updated_after: datetime,
) -> _RunSummary:
    count, oldest_updated_at = (
        await session.execute(
            sa.select(
                sa.func.count(sa.distinct(FlowRuns.id)),
                sa.func.min(FlowRuns.updated_at),
            )
            .select_from(FlowRuns)
            .join(FlowStepAttempts, FlowStepAttempts.flow_run_id == FlowRuns.id)
            .where(FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES))
            .where(FlowRuns.updated_at >= updated_after)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
        )
    ).one()
    return _RunSummary(
        count=int(count or 0),
        oldest_anchor_at=_normalize_datetime(oldest_updated_at),
    )


async def _load_expired_review_checkpoint_summary(
    *,
    session: AsyncSession,
    expires_before: datetime,
) -> _ReviewCheckpointExpirySummary:
    reconcilable_states = tuple(
        state.value for state in RECONCILABLE_REVIEW_CHECKPOINT_STATES
    )
    count, oldest_expires_at = (
        await session.execute(
            sa.select(
                sa.func.count(FlowRunReviewCheckpoints.id),
                sa.func.min(FlowRunReviewCheckpoints.expires_at),
            )
            .select_from(FlowRunReviewCheckpoints)
            .join(
                FlowRuns,
                sa.and_(
                    FlowRuns.id == FlowRunReviewCheckpoints.flow_run_id,
                    FlowRuns.tenant_id == FlowRunReviewCheckpoints.tenant_id,
                ),
            )
            .where(FlowRunReviewCheckpoints.state.in_(reconcilable_states))
            .where(FlowRunReviewCheckpoints.expires_at <= expires_before)
            .where(FlowRuns.status == FlowRunStatus.AWAITING_REVIEW.value)
        )
    ).one()
    return _ReviewCheckpointExpirySummary(
        count=int(count or 0),
        oldest_expires_at=_normalize_datetime(oldest_expires_at),
    )


async def _load_terminal_runs_with_active_step_results_summary(
    *,
    session: AsyncSession,
    updated_after: datetime,
) -> _RunSummary:
    count, oldest_updated_at = (
        await session.execute(
            sa.select(
                sa.func.count(sa.distinct(FlowRuns.id)),
                sa.func.min(FlowRuns.updated_at),
            )
            .select_from(FlowRuns)
            .join(FlowStepResults, FlowStepResults.flow_run_id == FlowRuns.id)
            .where(FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES))
            .where(FlowRuns.updated_at >= updated_after)
            .where(FlowStepResults.status.in_(ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES))
        )
    ).one()
    return _RunSummary(
        count=int(count or 0),
        oldest_anchor_at=_normalize_datetime(oldest_updated_at),
    )


async def _load_audit_outbox_summary(
    *,
    session: AsyncSession,
    backlog_before: datetime,
) -> _AuditOutboxSummary:
    pending_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(FlowRunAuditOutbox)
        .where(
            FlowRunAuditOutbox.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
        )
    )
    backlog_count, oldest_backlog_created_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRunAuditOutbox.created_at),
            )
            .select_from(FlowRunAuditOutbox)
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .where(
                sa.or_(
                    FlowRunAuditOutbox.next_delivery_at.is_(None),
                    FlowRunAuditOutbox.next_delivery_at <= backlog_before,
                )
            )
        )
    ).one()
    dead_lettered_count, oldest_dead_lettered_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRunAuditOutbox.dead_lettered_at),
            )
            .select_from(FlowRunAuditOutbox)
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            )
        )
    ).one()
    return _AuditOutboxSummary(
        pending_count=int(pending_count or 0),
        delivery_backlog_count=int(backlog_count or 0),
        oldest_backlog_created_at=_normalize_datetime(oldest_backlog_created_at),
        dead_lettered_count=int(dead_lettered_count or 0),
        oldest_dead_lettered_at=_normalize_datetime(oldest_dead_lettered_at),
    )


async def _load_webhook_outbox_summary(
    *,
    session: AsyncSession,
    backlog_before: datetime,
    now: datetime,
) -> _WebhookOutboxSummary:
    pending_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(FlowRunWebhookDeliveries)
        .where(
            FlowRunWebhookDeliveries.delivery_status
            == FlowOutboxDeliveryStatus.PENDING.value
        )
    )
    backlog_count, oldest_backlog_created_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRunWebhookDeliveries.created_at),
            )
            .select_from(FlowRunWebhookDeliveries)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .where(
                sa.or_(
                    FlowRunWebhookDeliveries.next_delivery_at.is_(None),
                    FlowRunWebhookDeliveries.next_delivery_at <= backlog_before,
                )
            )
            .where(
                sa.or_(
                    FlowRunWebhookDeliveries.claim_token.is_(None),
                    FlowRunWebhookDeliveries.claim_expires_at <= backlog_before,
                )
            )
        )
    ).one()
    expired_claim_count, oldest_expired_claim_expires_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRunWebhookDeliveries.claim_expires_at),
            )
            .select_from(FlowRunWebhookDeliveries)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .where(FlowRunWebhookDeliveries.claim_token.is_not(None))
            .where(FlowRunWebhookDeliveries.claim_expires_at <= now)
        )
    ).one()
    dead_lettered_count, oldest_dead_lettered_at = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(FlowRunWebhookDeliveries.dead_lettered_at),
            )
            .select_from(FlowRunWebhookDeliveries)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            )
        )
    ).one()
    return _WebhookOutboxSummary(
        pending_count=int(pending_count or 0),
        delivery_backlog_count=int(backlog_count or 0),
        oldest_backlog_created_at=_normalize_datetime(oldest_backlog_created_at),
        expired_claim_count=int(expired_claim_count or 0),
        oldest_expired_claim_expires_at=_normalize_datetime(
            oldest_expired_claim_expires_at
        ),
        dead_lettered_count=int(dead_lettered_count or 0),
        oldest_dead_lettered_at=_normalize_datetime(oldest_dead_lettered_at),
    )


def _flow_runtime_health_flags(
    *,
    snapshot: FlowRuntimeHealthSnapshot,
    stale_running_age_seconds: int | None,
    expired_review_checkpoint_age_seconds: int | None,
    policy: FlowRuntimeHealthPolicy,
) -> list[FlowRuntimeHealthFlag]:
    flags: list[FlowRuntimeHealthFlag] = []
    if snapshot.stale_queued_count > 0:
        flags.append(FlowRuntimeHealthFlag.STALE_QUEUED_RUNS)
    if snapshot.accepted_dispatch_exhausted_count > 0:
        flags.append(FlowRuntimeHealthFlag.ACCEPTED_DISPATCH_EXHAUSTED)
    if snapshot.stale_running_count > 0:
        if (
            stale_running_age_seconds is not None
            and stale_running_age_seconds > policy.stale_running_unhealthy_after_seconds
        ):
            flags.append(FlowRuntimeHealthFlag.STALE_RUNNING_RECONCILER_LAG)
        else:
            flags.append(FlowRuntimeHealthFlag.STALE_RUNNING_RUNS)
    if snapshot.expired_review_checkpoint_count > 0:
        if (
            expired_review_checkpoint_age_seconds is not None
            and expired_review_checkpoint_age_seconds
            > policy.review_expiry_unhealthy_after_seconds
        ):
            flags.append(FlowRuntimeHealthFlag.REVIEW_EXPIRY_RECONCILER_LAG)
        else:
            flags.append(FlowRuntimeHealthFlag.EXPIRED_REVIEW_CHECKPOINTS)
    if snapshot.terminal_runs_with_open_attempts_count > 0:
        flags.append(FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_OPEN_ATTEMPTS)
    if snapshot.terminal_runs_with_active_step_results_count > 0:
        flags.append(FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS)
    if snapshot.audit_outbox_delivery_backlog_count > 0:
        flags.append(FlowRuntimeHealthFlag.AUDIT_OUTBOX_DELIVERY_BACKLOG)
    if snapshot.audit_outbox_dead_lettered_count > 0:
        flags.append(FlowRuntimeHealthFlag.AUDIT_OUTBOX_DEAD_LETTERS)
    if snapshot.webhook_outbox_delivery_backlog_count > 0:
        flags.append(FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DELIVERY_BACKLOG)
    if snapshot.webhook_outbox_expired_claim_count > 0:
        flags.append(FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_EXPIRED_CLAIMS)
    if snapshot.webhook_outbox_dead_lettered_count > 0:
        flags.append(FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DEAD_LETTERS)
    return flags


def _flow_runtime_health_status(
    *,
    probe: FlowRuntimeProbe,
    status_flags: list[FlowRuntimeHealthFlag],
) -> FlowRuntimeHealthStatus:
    if not probe.db_query_ok:
        return FlowRuntimeHealthStatus.UNKNOWN
    unhealthy_flags = {
        FlowRuntimeHealthFlag.ACCEPTED_DISPATCH_EXHAUSTED,
        FlowRuntimeHealthFlag.STALE_RUNNING_RECONCILER_LAG,
        FlowRuntimeHealthFlag.REVIEW_EXPIRY_RECONCILER_LAG,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_OPEN_ATTEMPTS,
        FlowRuntimeHealthFlag.TERMINAL_RUNS_WITH_ACTIVE_STEP_RESULTS,
        FlowRuntimeHealthFlag.AUDIT_OUTBOX_DEAD_LETTERS,
        FlowRuntimeHealthFlag.WEBHOOK_OUTBOX_DEAD_LETTERS,
    }
    if any(flag in unhealthy_flags for flag in status_flags):
        return FlowRuntimeHealthStatus.UNHEALTHY
    if status_flags:
        return FlowRuntimeHealthStatus.DEGRADED
    return FlowRuntimeHealthStatus.HEALTHY


def _flow_runtime_status_reason(*, status: FlowRuntimeHealthStatus) -> str:
    return {
        FlowRuntimeHealthStatus.HEALTHY: "Flow runtime DB signals are healthy.",
        FlowRuntimeHealthStatus.DEGRADED: "Flow runtime has recoverable stale run, review checkpoint, or outbox signals.",
        FlowRuntimeHealthStatus.UNHEALTHY: "Flow runtime has accepted dispatch exhaustion, stale reconciliation lag, review expiry lag, terminal-run integrity issues, or outbox dead letters.",
        FlowRuntimeHealthStatus.UNKNOWN: "Flow runtime DB signals could not be read.",
    }[status]


def _age_seconds(now: datetime, timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    normalized_timestamp = _normalize_datetime(timestamp)
    if normalized_timestamp is None:
        return None
    return max(0, int((now - normalized_timestamp).total_seconds()))


def _normalize_datetime(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
