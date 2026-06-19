import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.data_retention.constants import (
    MIN_RETENTION_DAYS,
    ORPHANED_SESSION_CLEANUP_DAYS,
)
from intric.database.tables.app_table import AppRuns, Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_log_table import AuditLog as AuditLogTable
from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from intric.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from intric.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunRerunOperations,
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.flows.enums import (
    TERMINAL_FLOW_RUN_STATUS_VALUES,
    FlowRunRerunOperationStatus,
)
from intric.flows.flow_retention_policy import resolve_flow_retention_policy
from intric.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    FlowRetentionDataClass,
    FlowRetentionObjectType,
    FlowRetentionState,
    FlowRetentionTombstone,
    FlowRetentionTombstoneCounts,
    RunDebugAttemptRetentionCounts,
    RunDebugStepResultRetentionCounts,
    append_retention_tombstone,
    has_retention_tombstone,
)
from intric.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeRepository,
)

logger = logging.getLogger(__name__)

# Statement batch size for retention deletes; worker transaction loops decide commit scope.
RETENTION_BATCH_SIZE = 5000


def _sqlalchemy_affected_row_count(result: object) -> int:
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0


class FlowRuntimeCleanupCounts(TypedDict):
    debug_step_results: int
    debug_step_attempts: int
    flow_runs_purged: int
    flow_generated_files_deleted: int
    flow_webhook_deliveries_deleted: int
    flow_audit_outbox_rows_deleted: int
    flow_review_checkpoints_deleted: int
    flow_runs_skipped_undelivered_audit: int
    flow_runs_skipped_active_rerun: int


def _empty_flow_runtime_cleanup_counts() -> FlowRuntimeCleanupCounts:
    return {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "flow_runs_purged": 0,
        "flow_generated_files_deleted": 0,
        "flow_webhook_deliveries_deleted": 0,
        "flow_audit_outbox_rows_deleted": 0,
        "flow_review_checkpoints_deleted": 0,
        "flow_runs_skipped_undelivered_audit": 0,
        "flow_runs_skipped_active_rerun": 0,
    }


@dataclass(frozen=True)
class _FlowRuntimeRetentionAction:
    run_id: UUID
    tenant_id: UUID
    trace_id: UUID
    cutoff: datetime
    policy_source: str
    cleanup_timestamp: datetime


@dataclass(frozen=True, slots=True)
class FlowRunHistoryPurgeBlockedCounts:
    skipped_undelivered_audit: int = 0
    skipped_active_rerun: int = 0


@dataclass(frozen=True, slots=True)
class FlowDebugRedactionCounts:
    debug_step_results: int = 0
    debug_step_attempts: int = 0


class DataRetentionService:
    """Service for managing data retention and deletion based on hierarchical policies."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session

    async def cleanup_old_flow_runtime_data(self) -> FlowRuntimeCleanupCounts:
        now = datetime.now(timezone.utc)
        counts = _empty_flow_runtime_cleanup_counts()

        purge_counts = await self._purge_all_old_flow_run_history(now=now)
        counts["flow_runs_purged"] += purge_counts.flow_runs_purged
        counts["flow_generated_files_deleted"] += (
            purge_counts.flow_generated_files_deleted
        )
        counts["flow_webhook_deliveries_deleted"] += (
            purge_counts.flow_webhook_deliveries_deleted
        )
        counts["flow_audit_outbox_rows_deleted"] += (
            purge_counts.flow_audit_outbox_rows_deleted
        )
        counts["flow_review_checkpoints_deleted"] += (
            purge_counts.flow_review_checkpoints_deleted
        )
        blocked_counts = await self.count_blocked_flow_run_history_purge_candidates(
            now=now
        )
        counts["flow_runs_skipped_undelivered_audit"] += (
            blocked_counts.skipped_undelivered_audit
        )
        counts["flow_runs_skipped_active_rerun"] += blocked_counts.skipped_active_rerun

        if (
            blocked_counts.skipped_undelivered_audit > 0
            or blocked_counts.skipped_active_rerun > 0
        ):
            logger.info(
                "Skipped Flow run-history purge candidates "
                "(undelivered_audit=%s, active_rerun=%s)",
                blocked_counts.skipped_undelivered_audit,
                blocked_counts.skipped_active_rerun,
            )

        debug_counts = await self.redact_old_flow_debug_evidence(now=now)
        counts["debug_step_results"] += debug_counts.debug_step_results
        counts["debug_step_attempts"] += debug_counts.debug_step_attempts
        return counts

    async def delete_old_delivered_flow_audit_outbox_rows(self) -> int:
        audit_log_exists = (
            sa.select(sa.literal(1))
            .select_from(AuditLogTable)
            .where(AuditLogTable.id == FlowRunAuditOutbox.id)
            .exists()
        )
        base_subquery = sa.select(FlowRunAuditOutbox.id).where(
            sa.and_(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DELIVERED.value,
                sa.not_(audit_log_exists),
            )
        )

        total_deleted = 0
        while True:
            batch_subquery = base_subquery.order_by(FlowRunAuditOutbox.id).limit(
                RETENTION_BATCH_SIZE
            )
            # Audit logs own delivered audit lifetime; the outbox mirror is
            # removed only after audit retention deletes the matching audit row.
            result = await self.session.execute(
                sa.delete(FlowRunAuditOutbox).where(
                    FlowRunAuditOutbox.id.in_(batch_subquery)
                )
            )
            batch_deleted = _sqlalchemy_affected_row_count(result)
            if batch_deleted == 0:
                break
            total_deleted += batch_deleted
            logger.debug(
                "Deleted batch of %s delivered Flow audit outbox rows "
                "whose audit logs were already deleted by retention (total: %s)",
                batch_deleted,
                total_deleted,
            )

        if total_deleted > 0:
            logger.info(
                "Deleted %s delivered Flow audit outbox rows whose audit logs "
                "were already deleted by retention",
                total_deleted,
            )
        else:
            logger.debug("No delivered Flow audit outbox rows ready for cleanup")

        return total_deleted

    def _build_effective_retention_days(
        self,
        entity_retention_col: Any,
        space_retention_col: Any = Spaces.data_retention_days,
    ) -> Any:
        """
        Build COALESCE expression for hierarchical retention policy.

        The hierarchy is:
        1. Entity-level retention (Assistant/App specific)
        2. Space-level retention
        3. Tenant-level retention (if enabled)
        4. NULL (keep forever)

        Args:
            entity_retention_col: Column for entity-level retention (e.g., Assistants.data_retention_days)
            space_retention_col: Column for space-level retention (default: Spaces.data_retention_days)

        Returns:
            SQLAlchemy COALESCE expression
        """
        return sa.func.coalesce(
            entity_retention_col,
            space_retention_col,
            sa.case(
                (
                    AuditRetentionPolicy.conversation_retention_enabled.is_(True),
                    AuditRetentionPolicy.conversation_retention_days,
                ),
                else_=None,
            ),
        )

    async def _delete_old_records(
        self,
        record_table: type,
        entity_table: type,
        entity_retention_col: Any,
        entity_fk_col: Any,
        record_fk_col: Any,
        record_type: str,
    ) -> int:
        """
        Generic method to delete old records based on hierarchical retention policies.

        Uses batch deletion to prevent transaction timeouts on large datasets.

        Args:
            record_table: Table to delete from (e.g., Questions, AppRuns)
            entity_table: Parent entity table (e.g., Assistants, Apps)
            entity_retention_col: Entity's retention days column
            entity_fk_col: Foreign key column in entity table to Space
            record_fk_col: Foreign key column in record table to entity
            record_type: Human-readable record type for logging

        Returns:
            Number of records deleted
        """
        logger.info(
            f"Starting deletion of old {record_type} based on retention policies"
        )

        # Build effective retention days using hierarchy
        effective_retention_days = self._build_effective_retention_days(
            entity_retention_col
        )

        # Build base subquery to identify records to delete (will be limited per batch)
        base_subquery = cast(
            sa.Select[Any],
            sa.select(record_table.id)  # type: ignore[attr-defined]
            .join(entity_table, record_fk_col == entity_table.id)  # type: ignore[attr-defined]
            .join(Spaces, entity_fk_col == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    record_table.created_at  # type: ignore[attr-defined]
                    # make_interval signature: (years, months, weeks, days, hours, mins, secs)
                    < sa.func.now()
                    - sa.func.make_interval(0, 0, 0, effective_retention_days),
                )
            ),
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # Delete batch of records (ORDER BY ensures deterministic batch selection)
            batch_subquery = base_subquery.order_by(record_table.id).limit(  # type: ignore[attr-defined]
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(record_table).where(record_table.id.in_(batch_subquery))  # type: ignore[attr-defined]
            result = await self.session.execute(query)
            batch_deleted = _sqlalchemy_affected_row_count(result)

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} {record_type} (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(
                f"Deleted {total_deleted} old {record_type} based on retention policies"
            )
        else:
            logger.debug(f"No old {record_type} to delete based on retention policies")

        return total_deleted

    async def delete_old_questions(self) -> int:
        """
        Delete old questions using hierarchical retention policy resolution:
        1. Assistant-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of questions deleted
        """
        return await self._delete_old_records(
            record_table=Questions,
            entity_table=Assistants,
            entity_retention_col=Assistants.data_retention_days,
            entity_fk_col=Assistants.space_id,
            record_fk_col=Questions.assistant_id,
            record_type="questions",
        )

    async def delete_old_app_runs(self) -> int:
        """
        Delete old app runs using hierarchical retention policy resolution:
        1. App-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of app runs deleted
        """
        return await self._delete_old_records(
            record_table=AppRuns,
            entity_table=Apps,
            entity_retention_col=Apps.data_retention_days,
            entity_fk_col=Apps.space_id,
            record_fk_col=AppRuns.app_id,
            record_type="app runs",
        )

    async def delete_old_sessions(self) -> int:
        """
        Delete orphaned sessions that have no questions.

        Sessions without questions are deleted after ORPHANED_SESSION_CLEANUP_DAYS.
        Uses batch deletion to prevent transaction timeouts on large datasets.

        Returns:
            Number of sessions deleted
        """
        logger.info(
            f"Starting deletion of orphaned sessions older than {ORPHANED_SESSION_CLEANUP_DAYS} day(s)"
        )

        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(
            0, 0, 0, ORPHANED_SESSION_CLEANUP_DAYS
        )

        # Build base subquery to identify orphaned sessions (will be limited per batch)
        base_subquery = (
            sa.select(Sessions.id)
            .outerjoin(Questions, Sessions.id == Questions.session_id)
            .where(sa.and_(Sessions.created_at < cutoff_expr, Questions.id.is_(None)))
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # ORDER BY ensures deterministic batch selection
            batch_subquery = base_subquery.order_by(Sessions.id).limit(
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(Sessions).where(Sessions.id.in_(batch_subquery))
            result = await self.session.execute(query)
            batch_deleted = _sqlalchemy_affected_row_count(result)

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} orphaned sessions (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(f"Deleted {total_deleted} orphaned sessions")
        else:
            logger.debug("No orphaned sessions to delete")

        return total_deleted

    async def get_affected_questions_count_for_assistant(
        self, assistant_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted for a specific assistant."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(Questions.id)).where(
            sa.and_(
                Questions.assistant_id == assistant_id,
                Questions.created_at < cutoff_expr,
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_app(
        self, app_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted for a specific app."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(AppRuns.id)).where(
            sa.and_(AppRuns.app_id == app_id, AppRuns.created_at < cutoff_expr)
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def _purge_all_old_flow_run_history(
        self, *, now: datetime
    ) -> FlowRunHistoryPurgeCounts:
        total_counts = FlowRunHistoryPurgeCounts()

        while True:
            batch_counts = await self.purge_old_flow_run_history_batch(
                now=now,
                limit=RETENTION_BATCH_SIZE,
            )
            total_counts = total_counts.add(batch_counts)
            if batch_counts.flow_runs_purged == 0:
                break

        return total_counts

    async def purge_old_flow_run_history_batch(
        self, *, now: datetime, limit: int
    ) -> FlowRunHistoryPurgeCounts:
        run_ids = await self._select_flow_run_history_purge_batch(
            now=now,
            limit=limit,
        )
        return await FlowRunHistoryPurgeRepository(self.session).purge_run_history(
            run_ids
        )

    async def count_blocked_flow_run_history_purge_candidates(
        self, *, now: datetime
    ) -> FlowRunHistoryPurgeBlockedCounts:
        due_runs = self._build_due_flow_run_history_purge_query(now=now).subquery()
        run_id_col = due_runs.c.run_id
        undelivered_audit_exists = self._undelivered_flow_audit_exists(run_id_col)
        active_rerun_exists = self._active_flow_rerun_exists(run_id_col)

        undelivered_audit_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(due_runs)
            .where(undelivered_audit_exists)
        )
        active_rerun_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(due_runs)
            .where(sa.not_(undelivered_audit_exists))
            .where(active_rerun_exists)
        )

        return FlowRunHistoryPurgeBlockedCounts(
            skipped_undelivered_audit=undelivered_audit_count or 0,
            skipped_active_rerun=active_rerun_count or 0,
        )

    async def _select_flow_run_history_purge_batch(
        self, *, now: datetime, limit: int
    ) -> list[UUID]:
        retention_anchor = self._flow_run_history_retention_anchor()
        stmt = (
            self._build_due_flow_run_history_purge_query(now=now)
            .where(sa.not_(self._undelivered_flow_audit_exists(FlowRuns.id)))
            .where(sa.not_(self._active_flow_rerun_exists(FlowRuns.id)))
            .order_by(retention_anchor, FlowRuns.id)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    @staticmethod
    def _flow_run_history_retention_anchor() -> Any:
        return sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)

    def _build_due_flow_run_history_purge_query(
        self, *, now: datetime
    ) -> sa.Select[tuple[UUID]]:
        anchor = self._flow_run_history_retention_anchor()
        effective_retention_days = sa.func.coalesce(
            Flows.data_retention_days, Spaces.data_retention_days
        )
        effective_retention_days = sa.func.least(
            effective_retention_days,
            FlowClassificationRetentionPolicies.data_retention_days,
        )
        return (
            sa.select(FlowRuns.id.label("run_id"))
            .join(Flows, FlowRuns.flow_id == Flows.id)
            .join(Spaces, Flows.space_id == Spaces.id)
            .outerjoin(
                FlowClassificationRetentionPolicies,
                sa.and_(
                    FlowClassificationRetentionPolicies.security_classification_id
                    == Spaces.security_classification_id,
                    FlowClassificationRetentionPolicies.tenant_id == Spaces.tenant_id,
                ),
            )
            .where(
                sa.and_(
                    FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
                    effective_retention_days.isnot(None),
                    # Constant lower bound for ix_flow_runs_terminal_retention_anchor;
                    # safe because every retention source is >= MIN_RETENTION_DAYS.
                    anchor
                    <= sa.literal(now)
                    - sa.func.make_interval(0, 0, 0, MIN_RETENTION_DAYS),
                    anchor
                    <= sa.literal(now)
                    - sa.func.make_interval(0, 0, 0, effective_retention_days),
                )
            )
        )

    def _undelivered_flow_audit_exists(self, run_id_col: object) -> sa.Exists:
        return (
            sa.select(sa.literal(1))
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == run_id_col)
            .where(
                FlowRunAuditOutbox.delivery_status
                != FlowOutboxDeliveryStatus.DELIVERED.value
            )
            .exists()
        )

    def _active_flow_rerun_exists(self, run_id_col: object) -> sa.Exists:
        active_rerun_statuses = (
            FlowRunRerunOperationStatus.QUEUED.value,
            FlowRunRerunOperationStatus.RUNNING.value,
        )
        return (
            sa.select(sa.literal(1))
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == run_id_col)
            .where(FlowRunRerunOperations.status.in_(active_rerun_statuses))
            .exists()
        )

    async def redact_old_flow_debug_evidence(
        self, *, now: datetime
    ) -> FlowDebugRedactionCounts:
        total_counts = FlowDebugRedactionCounts()

        async for terminal_runs in self._iter_flow_debug_retention_rows(
            older_than=now - timedelta(days=1)
        ):
            debug_actions: dict[UUID, _FlowRuntimeRetentionAction] = {}

            for row in terminal_runs:
                anchor = row["retention_anchor"]
                if anchor is None:
                    continue
                run_id = cast(UUID, row["run_id"])
                tenant_id = cast(UUID, row["tenant_id"])
                trace_id = cast(UUID, row["trace_id"])
                policy = resolve_flow_retention_policy(row["flow_settings"])
                debug_retention_days = policy.debug_evidence_days()
                if debug_retention_days is not None and anchor <= now - timedelta(
                    days=debug_retention_days
                ):
                    debug_actions[run_id] = _FlowRuntimeRetentionAction(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        trace_id=trace_id,
                        cutoff=now - timedelta(days=debug_retention_days),
                        policy_source=(
                            "tenant.flow_settings.retention_policy."
                            "run_debug_evidence_days"
                        ),
                        cleanup_timestamp=now,
                    )

            if debug_actions:
                debug_counts = await self._cleanup_old_flow_debug_evidence(
                    debug_actions
                )
                total_counts = FlowDebugRedactionCounts(
                    debug_step_results=(
                        total_counts.debug_step_results
                        + debug_counts["debug_step_results"]
                    ),
                    debug_step_attempts=(
                        total_counts.debug_step_attempts
                        + debug_counts["debug_step_attempts"]
                    ),
                )

        return total_counts

    async def _iter_flow_debug_retention_rows(self, *, older_than: datetime):
        anchor = sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)
        last_run_id: UUID | None = None
        while True:
            stmt = (
                sa.select(
                    FlowRuns.id.label("run_id"),
                    FlowRuns.tenant_id.label("tenant_id"),
                    FlowRuns.trace_id.label("trace_id"),
                    anchor.label("retention_anchor"),
                    Tenants.flow_settings.label("flow_settings"),
                )
                .join(Tenants, FlowRuns.tenant_id == Tenants.id)
                .where(
                    sa.and_(
                        FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
                        anchor < older_than,
                        FlowRuns.id > last_run_id
                        if last_run_id is not None
                        else sa.true(),
                    )
                )
                .order_by(FlowRuns.id)
                .limit(RETENTION_BATCH_SIZE)
            )
            result = await self.session.execute(stmt)
            rows = [dict(row) for row in result.mappings().all()]
            if not rows:
                break
            last_run_id = cast(UUID, rows[-1]["run_id"])
            yield rows

    async def _cleanup_old_flow_debug_evidence(
        self, actions_by_run_id: dict[UUID, _FlowRuntimeRetentionAction]
    ) -> FlowRuntimeCleanupCounts:
        if not actions_by_run_id:
            return _empty_flow_runtime_cleanup_counts()

        step_result_stmt = sa.select(
            FlowStepResults.id,
            FlowStepResults.flow_run_id,
            FlowStepResults.input_payload_json,
            FlowStepResults.effective_prompt,
            FlowStepResults.output_payload_json,
            FlowStepResults.model_parameters_json,
        ).where(FlowStepResults.flow_run_id.in_(set(actions_by_run_id)))
        step_result_rows = await self.session.execute(step_result_stmt)
        debug_step_results = 0
        for row in step_result_rows.fetchall():
            action = actions_by_run_id[row.flow_run_id]
            pruned_output = _prune_debug_payload(row.output_payload_json)
            object_id = str(row.id)
            has_marker = has_retention_tombstone(
                pruned_output,
                data_class="run_debug_evidence",
                object_type="flow_step_result",
                object_id=object_id,
                retention_state="retention_purged",
            )
            counts = _debug_tombstone_counts(row, row.output_payload_json)
            needs_update = (
                any(
                    value is not None
                    for value in (
                        row.input_payload_json,
                        row.effective_prompt,
                        row.model_parameters_json,
                    )
                )
                or pruned_output != row.output_payload_json
                or (counts is not None and not has_marker)
            )
            if not needs_update:
                continue
            output_payload = (
                append_retention_tombstone(
                    pruned_output,
                    _build_retention_tombstone(
                        action=action,
                        data_class="run_debug_evidence",
                        object_type="flow_step_result",
                        object_id=object_id,
                        retention_state="retention_purged",
                        counts=counts,
                    ),
                )
                if counts is not None and not has_marker
                else pruned_output
            )
            result = await self.session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == row.id)
                .values(
                    input_payload_json=None,
                    effective_prompt=None,
                    output_payload_json=output_payload,
                    model_parameters_json=None,
                )
            )
            debug_step_results += _sqlalchemy_affected_row_count(result)

        attempt_stmt = sa.select(
            FlowStepAttempts.id,
            FlowStepAttempts.flow_run_id,
            FlowStepAttempts.provenance_json,
        ).where(
            sa.and_(
                FlowStepAttempts.flow_run_id.in_(set(actions_by_run_id)),
                FlowStepAttempts.provenance_json.is_not(None),
            )
        )
        attempt_rows = await self.session.execute(attempt_stmt)
        debug_step_attempts = 0
        for row in attempt_rows.fetchall():
            action = actions_by_run_id[row.flow_run_id]
            if _is_current_attempt_retention_marker(row.provenance_json):
                continue
            marker = _build_attempt_retention_marker(
                action=action,
                object_id=str(row.id),
                counts=RunDebugAttemptRetentionCounts(cleared_field_count=1),
            )
            attempt_result = await self.session.execute(
                sa.update(FlowStepAttempts)
                .where(FlowStepAttempts.id == row.id)
                .values(provenance_json=marker)
            )
            debug_step_attempts += _sqlalchemy_affected_row_count(attempt_result)

        counts = _empty_flow_runtime_cleanup_counts()
        counts["debug_step_results"] = debug_step_results
        counts["debug_step_attempts"] = debug_step_attempts
        return counts

    async def get_affected_questions_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted across all assistants in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .where(
                sa.and_(
                    Assistants.space_id == space_id,
                    Questions.created_at < cutoff_expr,
                    # Only count questions that don't have assistant-level retention
                    # (those would use their own retention policy)
                    Assistants.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted across all apps in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .where(
                sa.and_(
                    Apps.space_id == space_id,
                    AppRuns.created_at < cutoff_expr,
                    # Only count app runs that don't have app-level retention
                    Apps.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_total_count_for_tenant(
        self, tenant_id: UUID, retention_days: int
    ) -> dict[str, int]:
        """Get count of questions and app runs that would be deleted tenant-wide."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        # Count questions without assistant or space level retention
        questions_query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .join(Spaces, Assistants.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    Questions.created_at < cutoff_expr,
                    Assistants.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        # Count app runs without app or space level retention
        app_runs_query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .join(Spaces, Apps.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    AppRuns.created_at < cutoff_expr,
                    Apps.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        questions_result = await self.session.execute(questions_query)
        app_runs_result = await self.session.execute(app_runs_query)

        questions_count = questions_result.scalar() or 0
        app_runs_count = app_runs_result.scalar() or 0

        return {
            "questions": questions_count,
            "app_runs": app_runs_count,
            "total": questions_count + app_runs_count,
        }


def _prune_debug_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload_dict = cast(dict[str, Any], payload)
    pruned: dict[str, Any] = dict(payload_dict)
    pruned.pop("template_fill_debug", None)
    return pruned


def _debug_tombstone_counts(
    row: Any, output_payload: Any
) -> RunDebugStepResultRetentionCounts | None:
    cleared_fields = sum(
        1
        for value in (
            row.input_payload_json,
            row.effective_prompt,
            row.model_parameters_json,
        )
        if value is not None
    )
    pruned_output_keys = int(
        isinstance(output_payload, dict) and "template_fill_debug" in output_payload
    )
    if cleared_fields == 0 and pruned_output_keys == 0:
        return None
    return RunDebugStepResultRetentionCounts(
        cleared_field_count=cleared_fields,
        pruned_output_key_count=pruned_output_keys,
    )


def _build_retention_tombstone(
    *,
    action: _FlowRuntimeRetentionAction,
    data_class: FlowRetentionDataClass,
    object_type: FlowRetentionObjectType,
    object_id: str,
    retention_state: FlowRetentionState,
    counts: FlowRetentionTombstoneCounts,
) -> FlowRetentionTombstone:
    return FlowRetentionTombstone(
        tenant_id=str(action.tenant_id),
        run_id=str(action.run_id),
        trace_id=str(action.trace_id),
        data_class=data_class,
        object_type=object_type,
        object_id=object_id,
        policy_source=action.policy_source,
        cutoff=action.cutoff,
        actor_source=FLOW_RETENTION_ACTOR_SOURCE,
        counts=counts,
        timestamp=action.cleanup_timestamp,
        retention_state=retention_state,
    )


def _build_attempt_retention_marker(
    *,
    action: _FlowRuntimeRetentionAction,
    object_id: str,
    counts: RunDebugAttemptRetentionCounts,
) -> dict[str, Any]:
    return FlowAttemptRetentionMarker(
        tombstone=_build_retention_tombstone(
            action=action,
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=object_id,
            retention_state="retention_purged",
            counts=counts,
        )
    ).to_payload()


def _is_current_attempt_retention_marker(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        FlowAttemptRetentionMarker.model_validate(cast(dict[str, Any], payload))
    except ValueError:
        return False
    return True
