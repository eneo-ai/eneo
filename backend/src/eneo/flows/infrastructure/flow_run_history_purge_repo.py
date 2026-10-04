from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from eneo.data_retention.infrastructure.gallring_lock import (
    GallringSubject,
    acquire_shared,
)
from eneo.database.tables.app_table import AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderSessionFiles,
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    FlowTemplateAssets,
    FlowVersionFileReferences,
)
from eneo.database.tables.questions_table import QuestionsFiles
from eneo.files.file_repo import primary_file_content_size_expression
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_run_held_predicate

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
class _RuntimeSourceCandidate:
    run_id: UUID
    file_id: UUID


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

    async def _delete_released_live_transcripts(self, file_ids: set[UUID]) -> None:
        if not file_ids:
            return
        retained_run_reference = (
            sa.select(sa.literal(1))
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.file_id == FlowLiveTranscripts.bound_file_id)
            .exists()
        )
        await self.session.execute(
            sa.delete(FlowLiveTranscripts)
            .where(
                _uuid_is_in_batch(
                    FlowLiveTranscripts.bound_file_id,
                    file_ids,
                    parameter_name="released_live_transcript_file_ids",
                )
            )
            .where(sa.not_(retained_run_reference))
        )

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
        return await delete_unreferenced_files(self.session, file_ids)

    async def _primary_file_sizes(self, file_ids: set[UUID]) -> dict[UUID, int]:
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
        sizes: dict[UUID, int] = {}
        for file_id, raw_size_bytes in rows:
            size_bytes = cast(int | None, raw_size_bytes)
            if size_bytes is not None:
                sizes[file_id] = size_bytes
        if len(sizes) != len(file_ids):
            missing_count = len(file_ids) - len(sizes)
            raise RuntimeError(
                "Flow retention found "
                f"{missing_count} File row(s) without durable primary content"
            )
        return sizes


def _flow_template_asset_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowTemplateAssets)
        .where(FlowTemplateAssets.file_id == Files.id)
        .exists()
    )


def _flow_runtime_upload_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRuntimeUploadedFiles)
        .where(FlowRuntimeUploadedFiles.file_id == Files.id)
        .exists()
    )


def _flow_live_transcript_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowLiveTranscripts)
        .where(FlowLiveTranscripts.bound_file_id == Files.id)
        .exists()
    )


def _flow_run_step_input_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepInputFiles)
        .where(FlowRunStepInputFiles.file_id == Files.id)
        .exists()
    )


def _flow_run_step_result_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepResultFiles)
        .where(FlowRunStepResultFiles.file_id == Files.id)
        .exists()
    )


def _app_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AppsFiles)
        .where(AppsFiles.file_id == Files.id)
        .exists()
    )


def _app_run_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AppRunsFiles)
        .where(AppRunsFiles.file_id == Files.id)
        .exists()
    )


def _question_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(QuestionsFiles)
        .where(QuestionsFiles.file_id == Files.id)
        .exists()
    )


def _flow_version_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowVersionFileReferences)
        .where(FlowVersionFileReferences.file_id == Files.id)
        .exists()
    )


def _assistant_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AssistantsFiles)
        .where(AssistantsFiles.file_id == Files.id)
        .exists()
    )


def _builder_session_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(BuilderSessionFiles)
        .where(BuilderSessionFiles.file_id == Files.id)
        .exists()
    )


def _child_file_exists() -> sa.Exists:
    # A derived child blocks parent purge: cascading could delete a referenced child.
    child_files = aliased(Files)
    return (
        sa.select(sa.literal(1))
        .select_from(child_files)
        .where(child_files.parent_file_id == Files.id)
        .exists()
    )


_FILE_REFERENCE_EXISTS_BY_TABLE: Mapping[str, Callable[[], sa.Exists]] = (
    MappingProxyType(
        {
            Files.__tablename__: _child_file_exists,
            FlowTemplateAssets.__tablename__: _flow_template_asset_file_exists,
            FlowVersionFileReferences.__tablename__: _flow_version_file_exists,
            FlowRuntimeUploadedFiles.__tablename__: _flow_runtime_upload_file_exists,
            FlowLiveTranscripts.__tablename__: _flow_live_transcript_file_exists,
            FlowRunStepInputFiles.__tablename__: _flow_run_step_input_file_exists,
            FlowRunStepResultFiles.__tablename__: _flow_run_step_result_file_exists,
            AppsFiles.__tablename__: _app_file_exists,
            AppRunsFiles.__tablename__: _app_run_file_exists,
            QuestionsFiles.__tablename__: _question_file_exists,
            AssistantsFiles.__tablename__: _assistant_file_exists,
            BuilderSessionFiles.__tablename__: _builder_session_file_exists,
        }
    )
)
FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES = frozenset(
    _FILE_REFERENCE_EXISTS_BY_TABLE
)


def flow_file_reference_exists(
    *, excluding: frozenset[str] = frozenset()
) -> sa.ColumnElement[bool]:
    """The reference guard over `Files`: any owner except the excluded tables."""
    unknown = excluding - FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES
    if unknown:
        raise ValueError(f"Unknown file reference tables: {sorted(unknown)}")
    return sa.or_(
        *(
            reference_exists()
            for table_name, reference_exists in _FILE_REFERENCE_EXISTS_BY_TABLE.items()
            if table_name not in excluding
        )
    )


async def delete_unreferenced_files(
    session: AsyncSession, file_ids: set[UUID]
) -> set[UUID]:
    """Delete the files no owner references (children included), after locking them."""
    if not file_ids:
        return set()
    locked_file_ids = set(
        await session.scalars(
            sa.select(Files.id)
            .where(
                _uuid_is_in_batch(Files.id, file_ids, parameter_name="file_lock_ids")
            )
            .order_by(Files.id)
            .with_for_update(of=Files)
        )
    )
    if not locked_file_ids:
        return set()
    deleted_file_ids = await session.scalars(
        sa.delete(Files)
        .where(
            _uuid_is_in_batch(
                Files.id,
                locked_file_ids,
                parameter_name="unreferenced_file_delete_ids",
            )
        )
        .where(sa.not_(flow_file_reference_exists()))
        .returning(Files.id)
    )
    return set(deleted_file_ids.all())


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
