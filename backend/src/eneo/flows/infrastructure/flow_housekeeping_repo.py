"""Bounded statements of the nightly flows housekeeping (staging and waste data).

Every selection is a keyset page with a LIMIT over an index whose range a
literal cutoff bounds, after the step's durable cursor (GallringKeyset), so rows
that must stay are passed once per pass instead of starving the rows behind
them. Cutoffs use the deployment's settings
(docs/adr/single-tenant-assumption.md).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import (
    RetentionCategory,
    RetentionEntityKind,
    RetentionKeyset,
    RetentionPolicySource,
)
from eneo.data_retention.infrastructure.retention_lock import (
    RetentionSubject,
    acquire_shared,
)
from eneo.data_retention.infrastructure.retention_sql import (
    deployment_audit_retention_days,
    deployment_tenant_id,
    uuid_in,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
)
from eneo.database.tables.retention_tables import RetentionReceipts
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.flow_retention_policy import (
    DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS,
)
from eneo.flows.infrastructure.flow_abandonment_window import abandonment_cutoff
from eneo.flows.infrastructure.flow_retention_hold_repo import (
    flow_run_held_predicate,
    flow_runless_data_held_predicate,
)


@dataclass(frozen=True, slots=True)
class AbandonedUpload:
    file_id: UUID
    tenant_id: UUID
    flow_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AbandonmentPolicy:
    days: int
    source: RetentionPolicySource


@dataclass(frozen=True, slots=True)
class DeletableOutboxRow:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    delivered_at: datetime
    # An active hold covers the mirror's run or flow.
    held: bool


def _audit_log_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AuditLogTable)
        .where(AuditLogTable.id == FlowRunAuditOutbox.id)
        .exists()
    )


def _unattached_upload(now: datetime) -> tuple[sa.ColumnElement[bool], ...]:
    attached_to_run = (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepInputFiles)
        .where(
            FlowRunStepInputFiles.file_id == FlowRuntimeUploadedFiles.file_id,
            FlowRunStepInputFiles.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
        )
        .exists()
    )
    return (
        FlowRuntimeUploadedFiles.created_at
        <= abandonment_cutoff(now, deployment_tenant_id()),
        sa.not_(attached_to_run),
    )


class FlowHousekeepingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recorded_families(
        self, *, task: str, category: RetentionCategory, root_ids: Collection[UUID]
    ) -> set[UUID]:
        """Roots a receipt already covers (the unique key, one lookup per page).

        A receipt whose pruning started (a withdrawn one) no longer covers its root.
        """
        if not root_ids:
            return set()
        return set(
            await self.session.scalars(
                sa.select(RetentionReceipts.entity_id).where(
                    RetentionReceipts.task == task,
                    RetentionReceipts.entity_kind
                    == RetentionEntityKind.FILE_FAMILY.value,
                    RetentionReceipts.category == category.value,
                    uuid_in(RetentionReceipts.entity_id, root_ids),
                    RetentionReceipts.pruning_started_at.is_(None),
                )
            )
        )

    async def abandonment_policy(self) -> AbandonmentPolicy:
        days = await self.session.scalar(
            sa.select(Tenants.flow_runtime_upload_abandonment_days).where(
                Tenants.id == deployment_tenant_id()
            )
        )
        if days is None:
            return AbandonmentPolicy(
                DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS,
                RetentionPolicySource.DEFAULT,
            )
        return AbandonmentPolicy(days, RetentionPolicySource.TENANT)

    # Abandoned runtime uploads (anchor: the upload binding) ---------------------

    async def abandoned_uploads(
        self, *, now: datetime, after: RetentionKeyset | None, limit: int
    ) -> list[AbandonedUpload]:
        """Uploads never attached to a run and past the window, oldest first."""
        stmt = (
            sa.select(
                FlowRuntimeUploadedFiles.file_id,
                FlowRuntimeUploadedFiles.tenant_id,
                FlowRuntimeUploadedFiles.flow_id,
                FlowRuntimeUploadedFiles.created_at,
            )
            .where(*_unattached_upload(now))
            .order_by(
                FlowRuntimeUploadedFiles.created_at, FlowRuntimeUploadedFiles.file_id
            )
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(
                sa.tuple_(
                    FlowRuntimeUploadedFiles.created_at,
                    FlowRuntimeUploadedFiles.file_id,
                )
                > sa.tuple_(sa.literal(after.at), sa.literal(after.id))
            )
        return [
            AbandonedUpload(
                file_id=file_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                created_at=created_at,
            )
            for file_id, tenant_id, flow_id, created_at in (
                await self.session.execute(stmt)
            ).tuples()
        ]

    async def upload_eligible(self, file_id: UUID, *, now: datetime) -> bool:
        """Whether the upload still has its binding, unattached and past the window."""
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.select(sa.literal(1))
                    .select_from(FlowRuntimeUploadedFiles)
                    .where(
                        FlowRuntimeUploadedFiles.file_id == file_id,
                        *_unattached_upload(now),
                    )
                    .exists()
                )
            )
        )

    async def lock_upload(self, file_id: UUID, *, now: datetime) -> bool:
        """Lock the upload's file, then its binding (files -> uploads, as purge does).

        Skips rows another transaction holds: a binder's key-share lock means a run
        is attaching the upload. The binding lock rechecks eligibility, which closes
        the window between discovery and release.
        """
        if not await self._lock_file(file_id):
            return False
        binding_locked = await self.session.scalar(
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .where(
                FlowRuntimeUploadedFiles.file_id == file_id,
                *_unattached_upload(now),
            )
            .with_for_update(of=FlowRuntimeUploadedFiles, skip_locked=True)
        )
        return binding_locked is not None

    async def release_upload_binding(self, file_id: UUID) -> int:
        """Remove the discovery anchor (the binding): no run can attach the upload
        from here on. The rows deleted (one)."""
        return affected_row_count(
            await self.session.execute(
                sa.delete(FlowRuntimeUploadedFiles).where(
                    FlowRuntimeUploadedFiles.file_id == file_id
                )
            )
        )

    async def release_bound_transcripts(self, file_id: UUID) -> int:
        """Delete the live transcripts bound to the released upload (measured
        within the family cap before)."""
        return affected_row_count(
            await self.session.execute(
                sa.delete(FlowLiveTranscripts).where(
                    FlowLiveTranscripts.bound_file_id == file_id
                )
            )
        )

    async def _lock_file(self, file_id: UUID) -> bool:
        locked = await self.session.scalar(
            sa.select(Files.id)
            .where(Files.id == file_id)
            .with_for_update(of=Files, skip_locked=True)
        )
        return locked is not None

    # Holds --------------------------------------------------------------------

    async def lock_flow_history(self) -> None:
        """Serialize this chunk with hold and policy changes; first in every chunk.

        SHARED, so chunks run beside other deletions; a hold placed or changed
        waits for the chunk to commit, and the chunk waits for it, so every
        decision below reads the holds as they are when it deletes.
        """
        await acquire_shared(self.session, RetentionSubject.FLOW_HISTORY)

    async def held_flows(self, flow_ids: Collection[UUID]) -> set[UUID]:
        """Flows whose run-less data an active hold covers (flow_run_held_predicate)."""
        if not flow_ids:
            return set()
        flows = (
            sa.func.unnest(
                sa.literal(list(flow_ids), type_=ARRAY(PG_UUID(as_uuid=True)))
            )
            .table_valued("flow_id")
            .render_derived()
        )
        return set(
            await self.session.scalars(
                sa.select(flows.c.flow_id).where(
                    flow_runless_data_held_predicate(flow_id=flows.c.flow_id)
                )
            )
        )

    @staticmethod
    def receipt_held() -> sa.ColumnElement[bool]:
        """A held Flow or a remaining run's fence keeps the receipt's proof."""
        return sa.or_(
            flow_runless_data_held_predicate(flow_id=RetentionReceipts.flow_id),
            sa.exists(
                sa.select(FlowRuns.id).where(
                    FlowRuns.retention_receipt_id == RetentionReceipts.id
                )
            ),
        )

    # Delivered audit outbox mirrors -------------------------------------------

    async def deletable_audit_outbox(
        self,
        *,
        now: datetime,
        after: RetentionKeyset | None,
        limit: int,
    ) -> list[DeletableOutboxRow]:
        """Delivered mirrors older than the audit retention whose audit log is gone.

        One literal cutoff (the deployment's audit retention) bounds the range of
        the delivered-at index; a mirror whose audit log still exists is not
        selected, so every row of the page is deletable or held.
        """
        cutoff = sa.literal(now) - sa.func.make_interval(
            0, 0, 0, deployment_audit_retention_days()
        )
        stmt = (
            sa.select(
                FlowRunAuditOutbox.id,
                FlowRunAuditOutbox.tenant_id,
                FlowRunAuditOutbox.flow_id,
                FlowRunAuditOutbox.delivered_at,
                flow_run_held_predicate(
                    run_id=FlowRunAuditOutbox.flow_run_id,
                    flow_id=FlowRunAuditOutbox.flow_id,
                ),
            )
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DELIVERED.value,
                FlowRunAuditOutbox.delivered_at < cutoff,
                sa.not_(_audit_log_exists()),
            )
            .order_by(FlowRunAuditOutbox.delivered_at, FlowRunAuditOutbox.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(
                sa.tuple_(FlowRunAuditOutbox.delivered_at, FlowRunAuditOutbox.id)
                > sa.tuple_(sa.literal(after.at), sa.literal(after.id))
            )
        return [
            DeletableOutboxRow(
                id=row_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                delivered_at=at,
                held=bool(held),
            )
            for row_id, tenant_id, flow_id, at, held in (
                await self.session.execute(stmt)
            ).tuples()
            if at is not None
        ]

    async def delete_delivered_audit_outbox(
        self, ids: Collection[UUID]
    ) -> list[tuple[UUID, UUID]]:
        """Delete these delivered mirrors if their audit log is gone: (id, tenant id)."""
        if not ids:
            return []
        rows = await self.session.execute(
            sa.delete(FlowRunAuditOutbox)
            .where(
                uuid_in(FlowRunAuditOutbox.id, ids),
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DELIVERED.value,
                sa.not_(_audit_log_exists()),
            )
            .returning(FlowRunAuditOutbox.id, FlowRunAuditOutbox.tenant_id)
        )
        return list(rows.tuples())
