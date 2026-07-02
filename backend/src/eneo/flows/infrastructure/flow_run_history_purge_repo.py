from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from eneo.database.tables.app_table import AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderSessionFiles,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    FlowTemplateAssets,
)
from eneo.database.tables.questions_table import QuestionsFiles
from eneo.flows.infrastructure.flow_version_repo import (
    scan_flow_version_template_references,
)


@dataclass(frozen=True, slots=True)
class FlowRunHistoryPurgeCounts:
    flow_runs_purged: int = 0
    flow_generated_files_deleted: int = 0
    flow_webhook_deliveries_deleted: int = 0
    flow_audit_outbox_rows_deleted: int = 0
    flow_review_checkpoints_deleted: int = 0

    def add(self, other: "FlowRunHistoryPurgeCounts") -> "FlowRunHistoryPurgeCounts":
        return FlowRunHistoryPurgeCounts(
            flow_runs_purged=self.flow_runs_purged + other.flow_runs_purged,
            flow_generated_files_deleted=(
                self.flow_generated_files_deleted + other.flow_generated_files_deleted
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


class FlowRunHistoryPurgeRepository:
    """Reclaims Flow-owned files after retention selects safe tombstones."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def purge_run_history(
        self, run_ids: Sequence[UUID]
    ) -> FlowRunHistoryPurgeCounts:
        unique_run_ids = set(run_ids)
        if not unique_run_ids:
            return FlowRunHistoryPurgeCounts()

        candidate_generated_file_ids = await self._result_file_ids_for_runs(
            unique_run_ids
        )
        webhook_deliveries_deleted = await self._delete_webhook_deliveries(
            unique_run_ids
        )
        audit_outbox_rows_deleted = await self._delete_audit_outbox_rows(unique_run_ids)
        review_checkpoints_deleted = await self._delete_review_checkpoints(
            unique_run_ids
        )
        flow_runs_purged = await self._delete_flow_runs(unique_run_ids)
        generated_files_deleted = await self._delete_unreferenced_files(
            candidate_generated_file_ids
        )

        return FlowRunHistoryPurgeCounts(
            flow_runs_purged=flow_runs_purged,
            flow_generated_files_deleted=generated_files_deleted,
            flow_webhook_deliveries_deleted=webhook_deliveries_deleted,
            flow_audit_outbox_rows_deleted=audit_outbox_rows_deleted,
            flow_review_checkpoints_deleted=review_checkpoints_deleted,
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

        reclaimable_asset_ids = {
            candidate.asset_id for candidate in reclaimable_candidates[:limit]
        }
        deleted_file_id_rows = await self._delete_soft_deleted_template_assets(
            reclaimable_asset_ids
        )
        template_asset_files_deleted = await self._delete_unreferenced_files(
            set(deleted_file_id_rows)
        )
        return FlowTemplateAssetPurgeCounts(
            flow_template_assets_purged=len(deleted_file_id_rows),
            flow_template_asset_files_deleted=template_asset_files_deleted,
            flow_template_assets_skipped_published_reference=(
                skipped_published_reference
            ),
            flow_template_assets_skipped_undetermined_reference=(
                skipped_undetermined_reference
            ),
        )

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

    async def _result_file_ids_for_runs(self, run_ids: set[UUID]) -> set[UUID]:
        result = await self.session.scalars(
            sa.select(FlowRunStepResultFiles.file_id).where(
                FlowRunStepResultFiles.flow_run_id.in_(run_ids)
            )
        )
        return set(result.all())

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

    async def _delete_flow_runs(self, run_ids: set[UUID]) -> int:
        result = await self.session.execute(
            sa.delete(FlowRuns).where(FlowRuns.id.in_(run_ids))
        )
        return _affected_row_count(result)

    async def _delete_unreferenced_files(self, file_ids: set[UUID]) -> int:
        if not file_ids:
            return 0

        still_referenced = sa.or_(
            *(
                reference_exists()
                for reference_exists in _FILE_REFERENCE_EXISTS_BY_TABLE.values()
            )
        )
        result = await self.session.execute(
            sa.delete(Files)
            .where(Files.id.in_(file_ids))
            .where(sa.not_(still_referenced))
        )
        return _affected_row_count(result)


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
            FlowRuntimeUploadedFiles.__tablename__: _flow_runtime_upload_file_exists,
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


def _affected_row_count(result: object) -> int:
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0
