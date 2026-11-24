from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from eneo.data_retention.infrastructure.gallring_lock import (
    GallringSubject,
    acquire_shared,
)
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowProviderCalls,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpointEdits,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowStepTranscriptSources,
    FlowStepTranscriptWords,
    FlowTemplateAssets,
    FlowTranscriptCorrectionRevisions,
    FlowTranscriptCorrections,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_repo import primary_file_content_size_expression
from eneo.files.file_retention import FileRetentionReason
from eneo.files.file_usage import FileUsageRepository
from eneo.files.unused_file_cleanup import delete_unused_root_files
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_run_held_predicate
from eneo.flows.infrastructure.flow_version_repo import (
    scan_flow_version_template_references,
)

# Bound aggregate metadata and row locks independently from the run-page size.
# One already-oversized run still proceeds alone so cleanup cannot strand it.
_FLOW_RUN_HISTORY_PURGE_FILE_CANDIDATE_LIMIT = 10_000


@dataclass(frozen=True, slots=True)
class FlowRunHistoryPurgeCounts:
    flow_runs_considered: int = 0
    flow_runs_lock_deferred: int = 0
    flow_runs_purged: int = 0
    flow_generated_files_deleted: int = 0
    flow_runtime_source_candidates: int = 0
    flow_runtime_source_candidate_bytes: int = 0
    flow_runtime_source_bindings_deleted: int = 0
    flow_runtime_source_files_deleted: int = 0
    flow_runtime_source_bytes_deleted: int = 0
    flow_webhook_deliveries_deleted: int = 0
    flow_audit_outbox_rows_deleted: int = 0
    flow_review_checkpoints_deleted: int = 0

    def add(self, other: "FlowRunHistoryPurgeCounts") -> "FlowRunHistoryPurgeCounts":
        return FlowRunHistoryPurgeCounts(
            flow_runs_considered=(
                self.flow_runs_considered + other.flow_runs_considered
            ),
            flow_runs_lock_deferred=(
                self.flow_runs_lock_deferred + other.flow_runs_lock_deferred
            ),
            flow_runs_purged=self.flow_runs_purged + other.flow_runs_purged,
            flow_generated_files_deleted=(
                self.flow_generated_files_deleted + other.flow_generated_files_deleted
            ),
            flow_runtime_source_candidates=(
                self.flow_runtime_source_candidates
                + other.flow_runtime_source_candidates
            ),
            flow_runtime_source_candidate_bytes=(
                self.flow_runtime_source_candidate_bytes
                + other.flow_runtime_source_candidate_bytes
            ),
            flow_runtime_source_bindings_deleted=(
                self.flow_runtime_source_bindings_deleted
                + other.flow_runtime_source_bindings_deleted
            ),
            flow_runtime_source_files_deleted=(
                self.flow_runtime_source_files_deleted
                + other.flow_runtime_source_files_deleted
            ),
            flow_runtime_source_bytes_deleted=(
                self.flow_runtime_source_bytes_deleted
                + other.flow_runtime_source_bytes_deleted
            ),
            flow_webhook_deliveries_deleted=(
                self.flow_webhook_deliveries_deleted
                + other.flow_webhook_deliveries_deleted
            ),
            flow_audit_outbox_rows_deleted=(
                self.flow_audit_outbox_rows_deleted
                + other.flow_audit_outbox_rows_deleted
            ),
            flow_review_checkpoints_deleted=(
                self.flow_review_checkpoints_deleted
                + other.flow_review_checkpoints_deleted
            ),
        )


@dataclass(frozen=True, slots=True)
class FlowRunHistoryPurgeResult:
    counts: FlowRunHistoryPurgeCounts = FlowRunHistoryPurgeCounts()
    affected_flow_tenant_ids: frozenset[tuple[UUID, UUID]] = frozenset()

    def add(self, other: "FlowRunHistoryPurgeResult") -> "FlowRunHistoryPurgeResult":
        return FlowRunHistoryPurgeResult(
            counts=self.counts.add(other.counts),
            affected_flow_tenant_ids=(
                self.affected_flow_tenant_ids | other.affected_flow_tenant_ids
            ),
        )


@dataclass(frozen=True, slots=True)
class FlowTemplateAssetPurgeCounts:
    flow_template_assets_purged: int = 0
    flow_template_asset_files_deleted: int = 0
    flow_template_assets_skipped_published_reference: int = 0
    flow_template_assets_skipped_undetermined_reference: int = 0


@dataclass(frozen=True, slots=True)
class _SoftDeletedTemplateAssetCandidate:
    asset_id: UUID
    file_id: UUID
    flow_id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class _RuntimeSourceCandidate:
    run_id: UUID
    file_id: UUID


class FlowRunRemovalOutcome(StrEnum):
    REMOVED = "removed"
    # Gone, or the recheck under the lock refused it (a hold, an audit or a
    # webhook delivery that came after the selection).
    NOT_PURGEABLE = "not_purgeable"
    # Another transaction holds the run, a step result, an upload binding, a
    # live text or a file family.
    LOCKED = "locked"
    # The rows or files left in this call cannot fund it.
    SHORT = "short"
    # A file family is larger than the family cap.
    TOO_LARGE = "too_large"
    # The file owner refused a family for another reason.
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class FlowRunRemoval:
    """One run's removal: removed whole, or nothing (its savepoint rolled back).

    ``rows`` and ``files`` are the work charged, reads included; the counts
    below are what was removed and are zero unless the run was removed."""

    outcome: FlowRunRemovalOutcome
    rows: int
    files: int = 0
    tenant_id: UUID | None = None
    run_rows: int = 0
    uploads_released: int = 0
    live_transcripts_deleted: int = 0
    roots_deleted: int = 0
    files_deleted: int = 0
    file_dependencies_deleted: int = 0
    # The primary size of the released input Files, before storage confirms
    # that the bytes are gone.
    input_primary_bytes: int = 0
    # Files the run used that stay: in use elsewhere, gone already, or derived.
    files_kept: Counter[FileRetentionReason] = field(
        default_factory=Counter[FileRetentionReason]
    )


_REFUSALS = {
    FileRetentionReason.LOCKED: FlowRunRemovalOutcome.LOCKED,
    FileRetentionReason.INSUFFICIENT_BUDGET: FlowRunRemovalOutcome.SHORT,
    FileRetentionReason.FAMILY_EXCEEDS_BUDGET: FlowRunRemovalOutcome.TOO_LARGE,
}


def flow_run_owned_row_count(run_id: UUID, ceiling: int) -> sa.Select[tuple[int]]:
    """Every row that goes with a run, counting at most ``ceiling + 1``: the
    run, its direct children and the rows under its attempts and correction
    sets. Pinned to the foreign keys under ``flow_runs`` by a test, so a new
    child table is counted."""
    attempts = sa.select(FlowStepAttempts.id).where(
        FlowStepAttempts.flow_run_id == run_id
    )
    corrections = sa.select(FlowTranscriptCorrections.id).where(
        FlowTranscriptCorrections.flow_run_id == run_id
    )
    owned: list[sa.ColumnElement[bool]] = [
        FlowRuns.id == run_id,
        *(
            table.flow_run_id == run_id
            for table in (
                FlowStepResults,
                FlowStepAttempts,
                FlowRunReviewCheckpoints,
                FlowRunReviewCheckpointEdits,
                FlowRunStepInputFiles,
                FlowRunStepResultFiles,
                FlowRunAuditOutbox,
                FlowRunWebhookDeliveries,
                FlowTranscriptCorrections,
                FlowStepTranscriptWords,
                FlowStepTranscriptSources,
            )
        ),
        FlowStepAttemptResolvedInputs.flow_step_attempt_id.in_(attempts),
        FlowProviderCalls.flow_step_attempt_id.in_(attempts),
        FlowTranscriptCorrectionRevisions.correction_set_id.in_(corrections),
    ]
    # One LIMIT over every relation bounds the rows read, however large the run.
    rows = (
        sa.union_all(
            *(sa.select(sa.literal_column("1")).where(condition) for condition in owned)
        )
        .limit(ceiling + 1)
        .subquery("flow_run_rows")
    )
    return sa.select(sa.func.count()).select_from(rows)


def flow_run_undelivered_audit_exists(run_id_col: object) -> sa.Exists:
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


def flow_run_unresolved_webhook_exists(run_id_col: object) -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunWebhookDeliveries)
        .where(FlowRunWebhookDeliveries.flow_run_id == run_id_col)
        .where(
            FlowRunWebhookDeliveries.delivery_status
            == FlowOutboxDeliveryStatus.PENDING.value
        )
        .exists()
    )


class FlowRunHistoryPurgeRepository:
    """Reclaims Flow-owned files after retention selects safe tombstones."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def purge_run_history(
        self, run_ids: Sequence[UUID]
    ) -> FlowRunHistoryPurgeResult:
        ordered_run_ids = list(dict.fromkeys(run_ids))
        if not ordered_run_ids:
            return FlowRunHistoryPurgeResult()
        # A caller that selected without the lock still deletes only under it;
        # re-taking it in the same transaction is a no-op.
        await acquire_shared(self.session, GallringSubject.FLOW_HISTORY)
        bounded_run_ids = await self._candidate_bounded_run_ids(ordered_run_ids)
        unique_run_ids = set(bounded_run_ids)

        runtime_source_candidates = await self._runtime_source_candidates_for_runs(
            unique_run_ids
        )
        generated_file_ids_by_run = await self._result_file_ids_by_run(unique_run_ids)
        source_file_ids_by_run: dict[UUID, set[UUID]] = defaultdict(set)
        for candidate in runtime_source_candidates:
            source_file_ids_by_run[candidate.run_id].add(candidate.file_id)

        all_file_ids_by_run: dict[UUID, set[UUID]] = defaultdict(set)
        for run_id, file_ids in generated_file_ids_by_run.items():
            all_file_ids_by_run[run_id].update(file_ids)
        for run_id, file_ids in source_file_ids_by_run.items():
            all_file_ids_by_run[run_id].update(file_ids)

        locked_file_ids = await self._lock_files(
            {
                file_id
                for file_ids in all_file_ids_by_run.values()
                for file_id in file_ids
            },
            skip_locked=True,
        )
        locked_runtime_upload_ids = await self._lock_runtime_uploads(
            {
                file_id
                for file_ids in source_file_ids_by_run.values()
                for file_id in file_ids
                if file_id in locked_file_ids
            }
        )
        lockable_run_ids = {
            run_id
            for run_id in unique_run_ids
            if all_file_ids_by_run[run_id] <= locked_file_ids
            and source_file_ids_by_run[run_id] <= locked_runtime_upload_ids
        }
        locked_run_ids = await self._lock_runs(lockable_run_ids)
        purgeable_run_ids = await self._purgeable_locked_runs(locked_run_ids)
        lock_deferred_run_ids = (unique_run_ids - lockable_run_ids) | (
            lockable_run_ids - locked_run_ids
        )
        if not purgeable_run_ids:
            return FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=len(unique_run_ids),
                    flow_runs_lock_deferred=len(lock_deferred_run_ids),
                )
            )

        candidate_source_file_ids = {
            candidate.file_id
            for candidate in runtime_source_candidates
            if candidate.run_id in purgeable_run_ids
        }
        candidate_source_sizes = await self._primary_file_sizes(
            candidate_source_file_ids
        )
        candidate_generated_file_ids = {
            file_id
            for run_id in purgeable_run_ids
            for file_id in generated_file_ids_by_run[run_id]
        }
        webhook_deliveries_deleted = await self._delete_webhook_deliveries(
            purgeable_run_ids
        )
        audit_outbox_rows_deleted = await self._delete_audit_outbox_rows(
            purgeable_run_ids
        )
        review_checkpoints_deleted = await self._delete_review_checkpoints(
            purgeable_run_ids
        )
        deleted_flow_identities = await self._delete_flow_runs(purgeable_run_ids)
        deleted_generated_file_ids = await self._delete_unreferenced_files(
            candidate_generated_file_ids
        )
        # A live transcript bound to a source file lives as long as a run uses the file;
        # released first, or the file's live-transcript reference would keep it forever.
        await self._delete_released_live_transcripts(set(candidate_source_sizes))
        deleted_runtime_upload_ids = await self._delete_unreferenced_runtime_uploads(
            set(candidate_source_sizes)
        )
        deleted_runtime_source_file_ids = await self._delete_unreferenced_files(
            deleted_runtime_upload_ids
        )

        return FlowRunHistoryPurgeResult(
            counts=FlowRunHistoryPurgeCounts(
                flow_runs_considered=len(unique_run_ids),
                flow_runs_lock_deferred=len(lock_deferred_run_ids),
                flow_runs_purged=len(deleted_flow_identities),
                flow_generated_files_deleted=len(deleted_generated_file_ids),
                flow_runtime_source_candidates=len(candidate_source_sizes),
                flow_runtime_source_candidate_bytes=sum(
                    candidate_source_sizes.values()
                ),
                flow_runtime_source_bindings_deleted=len(deleted_runtime_upload_ids),
                flow_runtime_source_files_deleted=len(deleted_runtime_source_file_ids),
                flow_runtime_source_bytes_deleted=sum(
                    candidate_source_sizes[file_id]
                    for file_id in deleted_runtime_source_file_ids
                ),
                flow_webhook_deliveries_deleted=webhook_deliveries_deleted,
                flow_audit_outbox_rows_deleted=audit_outbox_rows_deleted,
                flow_review_checkpoints_deleted=review_checkpoints_deleted,
            ),
            affected_flow_tenant_ids=frozenset(deleted_flow_identities),
        )

    async def purge_due_run(
        self,
        run_id: UUID,
        *,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> FlowRunRemoval:
        """Remove one selected run whole, with its files, or nothing.

        The caller holds the gallring lock and passes ``max_rows >= 1``. Every
        lock is taken without waiting, so a row another transaction holds
        gives LOCKED instead of a wait that could end in a deadlock: a
        transcript edit locks the step result and then reaches the run through
        a foreign key, the opposite order. Anything but REMOVED rolls the
        savepoint back, so a run is never gone while one of its files can
        still be read. An error rolls back and propagates."""
        async with self.session.begin_nested() as unit:
            removal = await self._remove_run(
                run_id,
                max_rows=max_rows,
                max_files=max_files,
                max_family_rows=max_family_rows,
            )
            if removal.outcome is not FlowRunRemovalOutcome.REMOVED:
                await unit.rollback()
        return removal

    async def _remove_run(
        self,
        run_id: UUID,
        *,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> FlowRunRemoval:
        def stopped(outcome: FlowRunRemovalOutcome, rows: int) -> FlowRunRemoval:
            return FlowRunRemoval(outcome=outcome, rows=max(1, min(rows, max_rows)))

        # The run's lock also fences new child rows: their foreign key needs a
        # share lock on it.
        tenant_id = await self.session.scalar(
            sa.select(FlowRuns.tenant_id)
            .where(FlowRuns.id == run_id)
            .with_for_update(of=FlowRuns, skip_locked=True)
        )
        if tenant_id is None:
            held = await self.session.scalar(
                sa.select(sa.literal(True)).where(FlowRuns.id == run_id)
            )
            return stopped(
                FlowRunRemovalOutcome.LOCKED
                if held
                else FlowRunRemovalOutcome.NOT_PURGEABLE,
                2,
            )
        rows = 1
        # Counted up to the call's rows before anything else of the run is
        # read or locked: a run too large for them is refused at that cost.
        run_rows = cast(
            int,
            await self.session.scalar(
                flow_run_owned_row_count(run_id, ceiling=max_rows - rows)
            ),
        )
        rows += run_rows
        if rows > max_rows:
            return stopped(FlowRunRemovalOutcome.SHORT, rows)
        step_results = await self._lock_all(
            sa.select(FlowStepResults.id).where(FlowStepResults.flow_run_id == run_id),
            cap=run_rows,
        )
        if step_results is None:
            return stopped(FlowRunRemovalOutcome.LOCKED, rows)
        if not await self._purgeable_locked_runs({run_id}):
            return stopped(FlowRunRemovalOutcome.NOT_PURGEABLE, rows)

        result_file_ids = set(
            await self.session.scalars(
                sa.select(FlowRunStepResultFiles.file_id).where(
                    FlowRunStepResultFiles.flow_run_id == run_id
                )
            )
        )
        input_file_ids = set(
            await self.session.scalars(
                sa.select(FlowRunStepInputFiles.file_id).where(
                    FlowRunStepInputFiles.flow_run_id == run_id
                )
            )
        )
        for uses in (
            sa.select(FlowRuntimeUploadedFiles.file_id).where(
                _uuid_is_in_batch(
                    FlowRuntimeUploadedFiles.file_id,
                    input_file_ids,
                    parameter_name="run_binding_file_ids",
                )
            ),
            sa.select(FlowLiveTranscripts.id).where(
                FlowLiveTranscripts.bound_file_ids.overlap(
                    sa.bindparam(
                        "run_live_transcript_file_ids",
                        value=list(input_file_ids),
                        type_=postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                    )
                )
            ),
        ):
            locked = await self._lock_all(uses, cap=max_rows - rows)
            if locked is None:
                return stopped(FlowRunRemovalOutcome.LOCKED, rows)
            rows += locked
            if rows > max_rows:
                return stopped(FlowRunRemovalOutcome.SHORT, rows)
        if max_files == 0 and (result_file_ids or input_file_ids):
            return stopped(FlowRunRemovalOutcome.SHORT, rows)

        input_sizes = await self._primary_file_sizes(input_file_ids)
        await self._delete_webhook_deliveries({run_id})
        await self._delete_audit_outbox_rows({run_id})
        await self._delete_review_checkpoints({run_id})
        if not await self._delete_flow_runs({run_id}):
            raise RuntimeError("A locked, purgeable run was not deleted.")

        usage = FileUsageRepository(self.session)
        files = roots = members = references = 0
        kept: Counter[FileRetentionReason] = Counter()
        released_inputs: set[UUID] = set()

        async def release(file_id: UUID) -> FlowRunRemovalOutcome | None:
            nonlocal rows, files, roots, members, references
            result = await usage.delete_unused_root(
                file_id,
                max_rows=max_rows - rows,
                max_files=max_files - files,
                max_family_rows=max_family_rows,
            )
            rows += result.rows
            files += result.files
            if result.reason.is_refusal:
                return _REFUSALS.get(result.reason, FlowRunRemovalOutcome.REFUSED)
            if result.reason is FileRetentionReason.DELETED:
                roots += result.deleted_roots
                members += result.deleted_members
                references += result.deleted_references
                released_inputs.add(file_id)
            else:
                kept[result.reason] += 1
            return None

        for file_id in sorted(result_file_ids):
            refused = await release(file_id)
            if refused is not None:
                return stopped(refused, rows)
        # The live text and the binding use the input File; they go first.
        live_deleted = await self._delete_released_live_transcripts(input_file_ids)
        unbound = await self._delete_unreferenced_runtime_uploads(input_file_ids)
        for file_id in sorted(unbound):
            refused = await release(file_id)
            if refused is not None:
                return stopped(refused, rows)
        return FlowRunRemoval(
            outcome=FlowRunRemovalOutcome.REMOVED,
            rows=rows,
            files=files,
            tenant_id=tenant_id,
            run_rows=run_rows,
            uploads_released=len(unbound),
            live_transcripts_deleted=live_deleted,
            roots_deleted=roots,
            files_deleted=members,
            file_dependencies_deleted=references,
            input_primary_bytes=sum(
                input_sizes[file_id] for file_id in unbound & released_inputs
            ),
            files_kept=kept,
        )

    async def _lock_all(self, rows: sa.Select[tuple[UUID]], *, cap: int) -> int | None:
        """Lock every row ``rows`` selects without waiting, reading at most
        ``cap + 1``: their number (more than ``cap`` when they do not fit, and
        then none is locked), or None when another transaction holds one or a
        row arrived between the two reads."""
        bounded = rows.limit(cap + 1)
        total = cast(
            int,
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(bounded.subquery())
            ),
        )
        if total > cap:
            return total
        locked = len(
            (
                await self.session.scalars(bounded.with_for_update(skip_locked=True))
            ).all()
        )
        return total if locked == total else None

    async def purge_abandoned_runtime_uploads(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> FlowRunHistoryPurgeCounts:
        """Reclaim uploads only after the binder's key-share fence is clear.

        Candidate row locks serialize with binding, and the delete-time run-reference
        check closes the READ COMMITTED window between candidate selection and deletion.
        """
        candidate_file_ids = await self._abandoned_runtime_upload_candidate_file_ids(
            now=now,
            limit=limit,
        )
        if not candidate_file_ids:
            return FlowRunHistoryPurgeCounts()

        locked_file_ids = await self._lock_files(
            candidate_file_ids,
            skip_locked=True,
        )
        locked_runtime_upload_ids = await self._lock_abandoned_runtime_uploads(
            locked_file_ids,
            now=now,
        )
        candidate_sizes = await self._primary_file_sizes(locked_runtime_upload_ids)
        deleted_runtime_upload_ids = await self._delete_unreferenced_runtime_uploads(
            set(candidate_sizes)
        )
        deleted_file_ids = await self._delete_unreferenced_files(
            deleted_runtime_upload_ids
        )
        return FlowRunHistoryPurgeCounts(
            flow_runtime_source_candidates=len(candidate_sizes),
            flow_runtime_source_candidate_bytes=sum(candidate_sizes.values()),
            flow_runtime_source_bindings_deleted=len(deleted_runtime_upload_ids),
            flow_runtime_source_files_deleted=len(deleted_file_ids),
            flow_runtime_source_bytes_deleted=sum(
                candidate_sizes[file_id] for file_id in deleted_file_ids
            ),
        )

    async def purge_soft_deleted_template_assets(
        self,
        *,
        limit: int,
    ) -> FlowTemplateAssetPurgeCounts:
        candidates = await self._soft_deleted_template_asset_candidates()
        if not candidates:
            return FlowTemplateAssetPurgeCounts()

        candidates_by_flow: dict[
            tuple[UUID, UUID], list[_SoftDeletedTemplateAssetCandidate]
        ] = defaultdict(list)
        for candidate in candidates:
            candidates_by_flow[(candidate.tenant_id, candidate.flow_id)].append(
                candidate
            )

        reclaimable_candidates: list[_SoftDeletedTemplateAssetCandidate] = []
        skipped_published_reference = 0
        skipped_undetermined_reference = 0
        for (tenant_id, flow_id), group in candidates_by_flow.items():
            scan = await scan_flow_version_template_references(
                self.session,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
            if not scan.can_determine_safety:
                skipped_undetermined_reference += len(group)
                continue
            for candidate in group:
                if scan.may_reference(
                    template_asset_id=candidate.asset_id,
                    template_file_id=candidate.file_id,
                ):
                    skipped_published_reference += 1
                else:
                    reclaimable_candidates.append(candidate)

        limited_candidates = reclaimable_candidates[:limit]
        locked_file_ids = await self._lock_files(
            {candidate.file_id for candidate in limited_candidates},
            skip_locked=True,
        )
        reclaimable_asset_ids = {
            candidate.asset_id
            for candidate in limited_candidates
            if candidate.file_id in locked_file_ids
        }
        deleted_file_id_rows = await self._delete_soft_deleted_template_assets(
            reclaimable_asset_ids
        )
        deleted_template_asset_file_ids = await self._delete_unreferenced_files(
            set(deleted_file_id_rows)
        )
        return FlowTemplateAssetPurgeCounts(
            flow_template_assets_purged=len(deleted_file_id_rows),
            flow_template_asset_files_deleted=len(deleted_template_asset_file_ids),
            flow_template_assets_skipped_published_reference=(
                skipped_published_reference
            ),
            flow_template_assets_skipped_undetermined_reference=(
                skipped_undetermined_reference
            ),
        )

    async def _candidate_bounded_run_ids(
        self,
        ordered_run_ids: Sequence[UUID],
    ) -> list[UUID]:
        candidate_files = sa.union_all(
            sa.select(
                FlowRunStepInputFiles.flow_run_id.label("run_id"),
                FlowRunStepInputFiles.file_id.label("file_id"),
            ).where(FlowRunStepInputFiles.flow_run_id.in_(ordered_run_ids)),
            sa.select(
                FlowRunStepResultFiles.flow_run_id.label("run_id"),
                FlowRunStepResultFiles.file_id.label("file_id"),
            ).where(FlowRunStepResultFiles.flow_run_id.in_(ordered_run_ids)),
        ).subquery()
        rows = (
            await self.session.execute(
                sa.select(
                    candidate_files.c.run_id,
                    sa.func.count(sa.distinct(candidate_files.c.file_id)),
                ).group_by(candidate_files.c.run_id)
            )
        ).tuples()
        candidate_counts = {run_id: count for run_id, count in rows}

        bounded_run_ids: list[UUID] = []
        candidate_count = 0
        for run_id in ordered_run_ids:
            next_count = candidate_counts.get(run_id, 0)
            if (
                bounded_run_ids
                and candidate_count + next_count
                > _FLOW_RUN_HISTORY_PURGE_FILE_CANDIDATE_LIMIT
            ):
                break
            bounded_run_ids.append(run_id)
            candidate_count += next_count
            if candidate_count >= _FLOW_RUN_HISTORY_PURGE_FILE_CANDIDATE_LIMIT:
                break

        return bounded_run_ids

    async def _soft_deleted_template_asset_candidates(
        self,
    ) -> list[_SoftDeletedTemplateAssetCandidate]:
        rows = (
            await self.session.execute(
                sa.select(
                    FlowTemplateAssets.id,
                    FlowTemplateAssets.file_id,
                    FlowTemplateAssets.flow_id,
                    FlowTemplateAssets.tenant_id,
                )
                .where(FlowTemplateAssets.deleted_at.isnot(None))
                .order_by(FlowTemplateAssets.deleted_at, FlowTemplateAssets.id)
            )
        ).tuples()
        return [
            _SoftDeletedTemplateAssetCandidate(
                asset_id=asset_id,
                file_id=file_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
            )
            for asset_id, file_id, flow_id, tenant_id in rows
        ]

    async def _delete_soft_deleted_template_assets(
        self,
        asset_ids: set[UUID],
    ) -> list[UUID]:
        if not asset_ids:
            return []
        result = await self.session.scalars(
            sa.delete(FlowTemplateAssets)
            .where(FlowTemplateAssets.id.in_(asset_ids))
            .where(FlowTemplateAssets.deleted_at.isnot(None))
            .returning(FlowTemplateAssets.file_id)
        )
        return list(result.all())

    async def _runtime_source_candidates_for_runs(
        self, run_ids: set[UUID]
    ) -> list[_RuntimeSourceCandidate]:
        rows = (
            await self.session.execute(
                sa.select(
                    FlowRunStepInputFiles.flow_run_id,
                    FlowRunStepInputFiles.file_id,
                )
                .distinct()
                .where(FlowRunStepInputFiles.flow_run_id.in_(run_ids))
            )
        ).tuples()
        return [
            _RuntimeSourceCandidate(run_id=run_id, file_id=file_id)
            for run_id, file_id in rows
        ]

    async def _abandoned_runtime_upload_candidate_file_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> set[UUID]:
        rows = (
            await self.session.execute(
                sa.select(FlowRuntimeUploadedFiles.file_id)
                .join(
                    Files,
                    sa.and_(
                        Files.id == FlowRuntimeUploadedFiles.file_id,
                        Files.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
                    ),
                )
                .join(Tenants, Tenants.id == FlowRuntimeUploadedFiles.tenant_id)
                .where(
                    *_abandoned_runtime_upload_eligibility(now),
                )
                .order_by(
                    FlowRuntimeUploadedFiles.created_at,
                    FlowRuntimeUploadedFiles.file_id,
                )
                .limit(limit)
            )
        ).scalars()
        return set(rows.all())

    async def _lock_abandoned_runtime_uploads(
        self,
        file_ids: set[UUID],
        *,
        now: datetime,
    ) -> set[UUID]:
        if not file_ids:
            return set()
        result = await self.session.scalars(
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .join(
                Files,
                sa.and_(
                    Files.id == FlowRuntimeUploadedFiles.file_id,
                    Files.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
                ),
            )
            .join(Tenants, Tenants.id == FlowRuntimeUploadedFiles.tenant_id)
            .where(
                _uuid_is_in_batch(
                    FlowRuntimeUploadedFiles.file_id,
                    file_ids,
                    parameter_name="abandoned_runtime_upload_lock_file_ids",
                ),
                *_abandoned_runtime_upload_eligibility(now),
            )
            .order_by(FlowRuntimeUploadedFiles.file_id)
            .with_for_update(of=FlowRuntimeUploadedFiles, skip_locked=True)
        )
        return set(result.all())

    async def _result_file_ids_by_run(
        self, run_ids: set[UUID]
    ) -> dict[UUID, set[UUID]]:
        rows = (
            await self.session.execute(
                sa.select(
                    FlowRunStepResultFiles.flow_run_id,
                    FlowRunStepResultFiles.file_id,
                )
                .distinct()
                .where(FlowRunStepResultFiles.flow_run_id.in_(run_ids))
            )
        ).tuples()
        file_ids_by_run: dict[UUID, set[UUID]] = defaultdict(set)
        for run_id, file_id in rows:
            file_ids_by_run[run_id].add(file_id)
        return file_ids_by_run

    async def _lock_files(
        self,
        file_ids: set[UUID],
        *,
        skip_locked: bool,
    ) -> set[UUID]:
        if not file_ids:
            return set()
        result = await self.session.scalars(
            sa.select(Files.id)
            .where(
                _uuid_is_in_batch(
                    Files.id,
                    file_ids,
                    parameter_name="file_lock_ids",
                )
            )
            .order_by(Files.id)
            .with_for_update(of=Files, skip_locked=skip_locked)
        )
        return set(result.all())

    async def _lock_runtime_uploads(self, file_ids: set[UUID]) -> set[UUID]:
        if not file_ids:
            return set()
        result = await self.session.scalars(
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .where(
                _uuid_is_in_batch(
                    FlowRuntimeUploadedFiles.file_id,
                    file_ids,
                    parameter_name="runtime_upload_lock_file_ids",
                )
            )
            .order_by(FlowRuntimeUploadedFiles.file_id)
            .with_for_update(of=FlowRuntimeUploadedFiles, skip_locked=True)
        )
        return set(result.all())

    async def _lock_runs(self, run_ids: set[UUID]) -> set[UUID]:
        if not run_ids:
            return set()
        result = await self.session.scalars(
            sa.select(FlowRuns.id)
            .where(FlowRuns.id.in_(run_ids))
            .order_by(FlowRuns.id)
            .with_for_update(of=FlowRuns, skip_locked=True)
        )
        return set(result.all())

    async def _purgeable_locked_runs(self, run_ids: set[UUID]) -> set[UUID]:
        if not run_ids:
            return set()
        result = await self.session.scalars(
            sa.select(FlowRuns.id)
            .where(FlowRuns.id.in_(run_ids))
            .where(FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES))
            .where(sa.not_(flow_run_undelivered_audit_exists(FlowRuns.id)))
            .where(sa.not_(flow_run_unresolved_webhook_exists(FlowRuns.id)))
            .where(
                sa.not_(
                    flow_run_held_predicate(
                        run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                    )
                )
            )
        )
        return set(result.all())

    async def _delete_unreferenced_runtime_uploads(
        self, file_ids: set[UUID]
    ) -> set[UUID]:
        if not file_ids:
            return set()
        retained_run_reference = (
            sa.select(sa.literal(1))
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.file_id == FlowRuntimeUploadedFiles.file_id)
            .exists()
        )
        result = await self.session.scalars(
            sa.delete(FlowRuntimeUploadedFiles)
            .where(
                _uuid_is_in_batch(
                    FlowRuntimeUploadedFiles.file_id,
                    file_ids,
                    parameter_name="orphan_runtime_upload_file_ids",
                )
            )
            .where(sa.not_(retained_run_reference))
            .returning(FlowRuntimeUploadedFiles.file_id)
        )
        return set(result.all())

    async def _delete_released_live_transcripts(self, file_ids: set[UUID]) -> int:
        """Delete the live text of a recording once a run no longer uses any
        one of its parts: the text holds every part's words, so it goes with
        the first part whose audio may go, whichever part that is."""
        if not file_ids:
            return 0
        part = (
            sa.func.unnest(FlowLiveTranscripts.bound_file_ids)
            .table_valued("file_id")
            .render_derived(name="bound_part")
        )
        released_part = (
            sa.select(sa.literal(1))
            .select_from(part)
            .where(
                sa.not_(
                    sa.select(sa.literal(1))
                    .select_from(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.file_id == part.c.file_id)
                    .exists()
                )
            )
            .exists()
        )
        result = await self.session.execute(
            sa.delete(FlowLiveTranscripts)
            .where(
                FlowLiveTranscripts.bound_file_ids.overlap(
                    sa.bindparam(
                        "released_live_transcript_file_ids",
                        value=list(file_ids),
                        type_=postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                    )
                )
            )
            .where(released_part)
        )
        return _affected_row_count(result)

    async def _delete_webhook_deliveries(self, run_ids: set[UUID]) -> int:
        result = await self.session.execute(
            sa.delete(FlowRunWebhookDeliveries).where(
                FlowRunWebhookDeliveries.flow_run_id.in_(run_ids)
            )
        )
        return _affected_row_count(result)

    async def _delete_audit_outbox_rows(self, run_ids: set[UUID]) -> int:
        result = await self.session.execute(
            sa.delete(FlowRunAuditOutbox).where(
                FlowRunAuditOutbox.flow_run_id.in_(run_ids)
            )
        )
        return _affected_row_count(result)

    async def _delete_review_checkpoints(self, run_ids: set[UUID]) -> int:
        result = await self.session.execute(
            sa.delete(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.flow_run_id.in_(run_ids)
            )
        )
        return _affected_row_count(result)

    async def _delete_flow_runs(self, run_ids: set[UUID]) -> list[tuple[UUID, UUID]]:
        rows = (
            await self.session.execute(
                sa.delete(FlowRuns)
                .where(FlowRuns.id.in_(run_ids))
                .where(FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES))
                .returning(FlowRuns.flow_id, FlowRuns.tenant_id)
            )
        ).tuples()
        return list(rows.all())

    async def _delete_unreferenced_files(self, file_ids: set[UUID]) -> set[UUID]:
        # Files decides usage for the whole family, so a derived image or text
        # child goes with its root unless something still uses a member.
        return set(await delete_unused_root_files(self.session, file_ids))

    async def _primary_file_sizes(self, file_ids: set[UUID]) -> dict[UUID, int]:
        """The primary size of every requested File, 0 for one without primary
        content. The size only counts bytes; callers release by these keys, so
        a File without it is still released."""
        if not file_ids:
            return {}

        rows = (
            await self.session.execute(
                sa.select(
                    Files.id,
                    primary_file_content_size_expression().label("primary_size_bytes"),
                ).where(
                    _uuid_is_in_batch(
                        Files.id,
                        file_ids,
                        parameter_name="primary_file_size_ids",
                    )
                )
            )
        ).tuples()
        sizes = dict.fromkeys(file_ids, 0)
        for file_id, raw_size_bytes in rows:
            sizes[file_id] = cast(int | None, raw_size_bytes) or 0
        return sizes


def _abandoned_runtime_upload_eligibility(
    now: datetime,
) -> tuple[sa.ColumnElement[bool], ...]:
    attached_to_run = (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepInputFiles)
        .where(
            FlowRunStepInputFiles.file_id == FlowRuntimeUploadedFiles.file_id,
            FlowRunStepInputFiles.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
        )
        .exists()
    )
    horizon_due = FlowRuntimeUploadedFiles.created_at <= sa.literal(
        now
    ) - sa.func.make_interval(
        0,
        0,
        0,
        Tenants.flow_runtime_upload_abandonment_days,
    )
    return (
        Tenants.flow_runtime_upload_abandonment_days.is_not(None),
        horizon_due,
        sa.not_(attached_to_run),
    )


def _uuid_is_in_batch(
    column: sa.ColumnElement[UUID]
    | InstrumentedAttribute[UUID]
    | InstrumentedAttribute[UUID | None],
    values: set[UUID],
    *,
    parameter_name: str,
) -> sa.ColumnElement[bool]:
    """Use one UUID-array bind so large retention batches do not hit bind limits."""

    return column == sa.any_(
        sa.bindparam(
            parameter_name,
            value=list(values),
            type_=postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
        )
    )


def _affected_row_count(result: object) -> int:
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0
