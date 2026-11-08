import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.gallring_lock import (
    GallringSubject,
    acquire_shared,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowProviderCalls,
    FlowRunAuditOutbox,
    FlowRuns,
    Flows,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow_run_retention_policy import FlowRunRetentionMode
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.flow_retention_policy import resolve_flow_retention_policy
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_run_held_predicate
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeRepository,
    FlowRunHistoryPurgeResult,
    FlowTemplateAssetPurgeCounts,
    flow_run_undelivered_audit_exists,
    flow_run_unresolved_webhook_exists,
)
from eneo.flows.infrastructure.flow_run_retention_policy_query import (
    EffectiveFlowRunRetentionPolicySql,
    effective_flow_run_retention_policy_sql,
    flow_run_history_due_predicates,
)
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository

logger = logging.getLogger(__name__)

# Statement batch size for Flow retention deletes and scans; the caller's
# transaction decides commit scope.
RETENTION_BATCH_SIZE = 5000
FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW = 500


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
    skipped_unresolved_webhook: int = 0
    skipped_review_required: int = 0
    skipped_legal_hold: int = 0
    counted_runs: int = 0
    complete: bool = True


@dataclass(frozen=True, slots=True)
class TenantFlowRunHistoryPurgeResult:
    candidate_count: int
    purged_run_ids: tuple[UUID, ...]
    transcript_candidate_count: int
    transcript_purged_count: int
    blocked: FlowRunHistoryPurgeBlockedCounts


@dataclass(frozen=True, slots=True)
class FlowDebugRedactionCounts:
    debug_step_results: int = 0
    debug_step_attempts: int = 0
    debug_provider_calls: int = 0
    debug_resolved_input_aggregates: int = 0
    debug_resolved_input_edges: int = 0


class FlowRetentionRepository:
    """Removes and redacts Flow run data that Flow retention settings make due."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
            batch_deleted = affected_row_count(result)
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

    async def purge_abandoned_flow_runtime_uploads(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> FlowRunHistoryPurgeCounts:
        """Reclaim runtime uploads never bound to a run, past their horizon.

        The tenant's abandonment horizon and its byte-accurate impact preview are
        operator-facing settings, so this step has to run wherever flow retention
        actually runs.
        """
        return await FlowRunHistoryPurgeRepository(
            self.session
        ).purge_abandoned_runtime_uploads(now=now, limit=limit)

    async def purge_soft_deleted_flow_template_assets(
        self,
        *,
        limit: int,
    ) -> FlowTemplateAssetPurgeCounts:
        return await FlowRunHistoryPurgeRepository(
            self.session
        ).purge_soft_deleted_template_assets(limit=limit)

    async def purge_old_flow_run_history_batch(
        self, *, now: datetime, limit: int
    ) -> FlowRunHistoryPurgeResult:
        run_ids = await self._select_flow_run_history_purge_batch(
            now=now,
            limit=limit,
        )
        return await FlowRunHistoryPurgeRepository(self.session).purge_run_history(
            run_ids
        )

    async def count_blocked_flow_run_history_purge_candidates(
        self,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> FlowRunHistoryPurgeBlockedCounts:
        _, preserve = self._flow_run_history_purge_eligibility_predicates()
        anchor = self._flow_run_history_retention_anchor()
        held = flow_run_held_predicate(run_id=FlowRuns.id, flow_id=FlowRuns.flow_id)
        due = self._build_due_flow_run_history_purge_query(
            now=now,
            tenant_id=tenant_id,
            space_id=space_id,
            flow_id=flow_id,
            include_blocked=True,
        )
        # Held runs are counted apart, bounded like the window, so they never
        # push runs with a real blocker out of it.
        held_count = (
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(
                    due.where(held)
                    .limit(FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW + 1)
                    .subquery()
                )
            )
            or 0
        )
        due_runs = (
            due.where(sa.not_(held))
            .add_columns(preserve.label("preserve"), anchor.label("anchor"))
            .order_by(anchor, FlowRuns.id)
            .limit(FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW + 1)
            .subquery()
        )
        run_id_col = due_runs.c.run_id
        undelivered_audit_exists = flow_run_undelivered_audit_exists(run_id_col)
        unresolved_webhook_exists = flow_run_unresolved_webhook_exists(run_id_col)
        rows = (
            await self.session.execute(
                sa.select(
                    due_runs.c.preserve,
                    undelivered_audit_exists,
                    unresolved_webhook_exists,
                )
                .select_from(due_runs)
                .order_by(due_runs.c.anchor, due_runs.c.run_id)
            )
        ).all()
        window = rows[:FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW]
        audit_count = webhook_count = review_count = 0
        for preserves_history, undelivered_audit, unresolved_webhook in window:
            if not preserves_history:
                review_count += 1
            elif undelivered_audit:
                audit_count += 1
            elif unresolved_webhook:
                webhook_count += 1

        return FlowRunHistoryPurgeBlockedCounts(
            skipped_undelivered_audit=audit_count,
            skipped_unresolved_webhook=webhook_count,
            skipped_review_required=review_count,
            skipped_legal_hold=min(
                held_count, FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW
            ),
            counted_runs=len(window),
            complete=(
                len(rows) <= FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW
                and held_count <= FLOW_RUN_HISTORY_PURGE_DIAGNOSTIC_WINDOW
            ),
        )

    async def purge_due_flow_run_history_for_tenant(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int,
        dry_run: bool,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> TenantFlowRunHistoryPurgeResult:
        if not 1 <= limit <= 500:
            raise ValueError("Flow history purge limit must be between 1 and 500.")
        if space_id is not None and flow_id is not None:
            raise ValueError("Flow history purge accepts only one scope.")
        if not dry_run:
            # Before any read or row lock: policy and hold changes commit either
            # before this selection or after this transaction.
            await acquire_shared(self.session, GallringSubject.FLOW_HISTORY)
        blocked = await self.count_blocked_flow_run_history_purge_candidates(
            now=now, tenant_id=tenant_id, space_id=space_id, flow_id=flow_id
        )
        candidates = self._build_flow_run_history_purge_batch_query(
            now=now,
            limit=limit,
            tenant_id=tenant_id,
            space_id=space_id,
            flow_id=flow_id,
        )
        # Own candidate run locks before deriving the deleted IDs so another
        # administrator's concurrent purge cannot enter this audit receipt.
        if not dry_run:
            candidates = candidates.with_for_update(of=FlowRuns, skip_locked=True)
        run_ids = list((await self.session.scalars(candidates)).all())
        purged_run_ids: tuple[UUID, ...] = ()
        if not dry_run and run_ids:
            await FlowRunHistoryPurgeRepository(self.session).purge_run_history(run_ids)
            remaining = set(
                (
                    await self.session.scalars(
                        sa.select(FlowRuns.id).where(FlowRuns.id.in_(run_ids))
                    )
                ).all()
            )
            purged_run_ids = tuple(
                run_id for run_id in run_ids if run_id not in remaining
            )
        transcripts = await LiveTranscriptRepository(
            self.session
        ).delete_expired_unbound(
            tenant_id=tenant_id,
            now=now,
            limit=limit,
            dry_run=dry_run,
            space_id=space_id,
            flow_id=flow_id,
        )
        return TenantFlowRunHistoryPurgeResult(
            candidate_count=len(run_ids),
            purged_run_ids=purged_run_ids,
            transcript_candidate_count=transcripts.candidate_count,
            transcript_purged_count=transcripts.purged_count,
            blocked=blocked,
        )

    async def _select_flow_run_history_purge_batch(
        self, *, now: datetime, limit: int
    ) -> list[UUID]:
        result = await self.session.scalars(
            self._build_flow_run_history_purge_batch_query(now=now, limit=limit)
        )
        return list(result.all())

    def _build_flow_run_history_purge_batch_query(
        self,
        *,
        now: datetime,
        limit: int,
        tenant_id: UUID | None = None,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> sa.Select[tuple[UUID]]:
        retention_anchor = self._flow_run_history_retention_anchor()
        return (
            self._build_due_flow_run_history_purge_query(
                now=now, tenant_id=tenant_id, space_id=space_id, flow_id=flow_id
            )
            .where(sa.not_(flow_run_undelivered_audit_exists(FlowRuns.id)))
            .where(sa.not_(flow_run_unresolved_webhook_exists(FlowRuns.id)))
            .where(
                sa.not_(
                    flow_run_held_predicate(
                        run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                    )
                )
            )
            .order_by(retention_anchor, FlowRuns.id)
            .limit(limit)
        )

    @staticmethod
    def _flow_run_history_retention_anchor() -> Any:
        return sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)

    def _build_due_flow_run_history_purge_query(
        self,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
        include_blocked: bool = False,
    ) -> sa.Select[tuple[UUID]]:
        anchor = self._flow_run_history_retention_anchor()
        effective_policy = self._effective_flow_run_history_policy_sql()
        terminal, preserve = self._flow_run_history_purge_eligibility_predicates()
        stmt = (
            sa.select(FlowRuns.id.label("run_id"))
            .join(
                Flows,
                sa.and_(
                    FlowRuns.flow_id == Flows.id, FlowRuns.tenant_id == Flows.tenant_id
                ),
            )
            .join(
                Spaces,
                sa.and_(
                    Flows.space_id == Spaces.id, Flows.tenant_id == Spaces.tenant_id
                ),
            )
            .join(Tenants, FlowRuns.tenant_id == Tenants.id)
            .where(
                terminal,
                *flow_run_history_due_predicates(
                    now=now, anchor=anchor, effective_days=effective_policy.days
                ),
            )
        )
        if not include_blocked:
            stmt = stmt.where(preserve)
        if tenant_id is not None:
            stmt = stmt.where(FlowRuns.tenant_id == tenant_id)
        if space_id is not None:
            stmt = stmt.where(Flows.space_id == space_id)
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        return stmt

    def _flow_run_history_purge_eligibility_predicates(
        self,
    ) -> tuple[sa.ColumnElement[bool], sa.ColumnElement[bool]]:
        return (
            FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
            self._effective_flow_run_history_policy_sql().mode
            == FlowRunRetentionMode.PRESERVE.value,
        )

    @staticmethod
    def _effective_flow_run_history_policy_sql() -> EffectiveFlowRunRetentionPolicySql:
        return effective_flow_run_retention_policy_sql(
            organization_mode=(
                Tenants.flow_run_history_retention_mode.__clause_element__()
            ),
            organization_days=(
                Tenants.flow_run_history_retention_days.__clause_element__()
            ),
            space_mode=(Spaces.flow_run_history_retention_mode.__clause_element__()),
            space_days=Spaces.flow_run_history_retention_days.__clause_element__(),
            flow_mode=Flows.flow_run_history_retention_mode.__clause_element__(),
            flow_days=Flows.flow_run_history_retention_days.__clause_element__(),
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
                        + debug_counts.debug_step_results
                    ),
                    debug_step_attempts=(
                        total_counts.debug_step_attempts
                        + debug_counts.debug_step_attempts
                    ),
                    debug_provider_calls=(
                        total_counts.debug_provider_calls
                        + debug_counts.debug_provider_calls
                    ),
                    debug_resolved_input_aggregates=(
                        total_counts.debug_resolved_input_aggregates
                        + debug_counts.debug_resolved_input_aggregates
                    ),
                    debug_resolved_input_edges=(
                        total_counts.debug_resolved_input_edges
                        + debug_counts.debug_resolved_input_edges
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
    ) -> FlowDebugRedactionCounts:
        if not actions_by_run_id:
            return FlowDebugRedactionCounts()

        # Redaction removes run content, so a legal hold stops it like any
        # deletion: under the gallring lock, held runs drop out here.
        await acquire_shared(self.session, GallringSubject.FLOW_HISTORY)
        run_ids = set(
            (
                await self.session.scalars(
                    sa.select(FlowRuns.id)
                    .where(FlowRuns.id.in_(list(actions_by_run_id)))
                    .where(
                        sa.not_(
                            flow_run_held_predicate(
                                run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                            )
                        )
                    )
                )
            ).all()
        )
        if not run_ids:
            return FlowDebugRedactionCounts()
        step_result_rows = await self.session.execute(
            sa.select(
                FlowStepResults.id,
                FlowStepResults.input_payload_json,
                FlowStepResults.effective_prompt,
                FlowStepResults.output_payload_json,
                FlowStepResults.model_parameters_json,
            ).where(FlowStepResults.flow_run_id.in_(run_ids))
        )
        debug_step_results = 0
        for row in step_result_rows:
            pruned_output = _prune_debug_payload(row.output_payload_json)
            if (
                row.input_payload_json is None
                and row.effective_prompt is None
                and row.model_parameters_json is None
                and pruned_output == row.output_payload_json
            ):
                continue
            result = await self.session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == row.id)
                .values(
                    input_payload_json=None,
                    effective_prompt=None,
                    output_payload_json=pruned_output,
                    model_parameters_json=None,
                )
            )
            debug_step_results += affected_row_count(result)

        attempt_ids = list(
            (
                await self.session.scalars(
                    sa.select(FlowStepAttempts.id).where(
                        FlowStepAttempts.flow_run_id.in_(run_ids)
                    )
                )
            ).all()
        )
        deleted_provider_calls = 0
        deleted_resolved_inputs = 0
        debug_step_attempts = 0
        if attempt_ids:
            provider_result = await self.session.execute(
                sa.delete(FlowProviderCalls).where(
                    FlowProviderCalls.flow_step_attempt_id.in_(attempt_ids)
                )
            )
            deleted_provider_calls = affected_row_count(provider_result)
            resolved_result = await self.session.execute(
                sa.delete(FlowStepAttemptResolvedInputs).where(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id.in_(attempt_ids)
                )
            )
            deleted_resolved_inputs = affected_row_count(resolved_result)
            attempt_result = await self.session.execute(
                sa.update(FlowStepAttempts)
                .where(FlowStepAttempts.id.in_(attempt_ids))
                .where(
                    sa.or_(
                        FlowStepAttempts.provenance_json.is_not(None),
                        FlowStepAttempts.input_payload_json.is_not(None),
                        FlowStepAttempts.output_payload_json.is_not(None),
                    )
                )
                .values(
                    provenance_json=None,
                    input_payload_json=None,
                    output_payload_json=None,
                )
            )
            debug_step_attempts = affected_row_count(attempt_result)

        return FlowDebugRedactionCounts(
            debug_step_results=debug_step_results,
            debug_step_attempts=debug_step_attempts,
            debug_provider_calls=deleted_provider_calls,
            debug_resolved_input_aggregates=deleted_resolved_inputs,
        )


def _prune_debug_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload_dict = cast(dict[str, Any], payload)
    pruned: dict[str, Any] = dict(payload_dict)
    pruned.pop("template_fill_debug", None)
    return pruned
