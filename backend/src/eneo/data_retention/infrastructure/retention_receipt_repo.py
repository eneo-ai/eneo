"""Retention receipts (deletion evidence), their manifests and physical-deletion tracking."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from eneo.data_retention.domain.retention import (
    FINAL_RECEIPT_PHASES,
    NON_FINAL_RECEIPT_PHASES,
    ManifestPosition,
    NewRetentionReceipt,
    PhysicalItemPage,
    PhysicalReceiptKey,
    PrunedReceipts,
    ReceiptItemDisposition,
    ReceiptPhase,
    ReceiptReason,
    ReceiptState,
    ReceiptUpdate,
    RetentionCategory,
    RetentionKeyset,
    RetentionReceipt,
    RetentionTrigger,
)
from eneo.data_retention.infrastructure.retention_sql import (
    deployment_audit_retention_days,
    uuid_in,
)
from eneo.database.tables.object_content_table import ObjectContents
from eneo.database.tables.retention_tables import (
    RetentionReceiptItems,
    RetentionReceipts,
)
from eneo.object_content.content import ContentState


def _receipt(row: RetentionReceipts) -> RetentionReceipt:
    return RetentionReceipt(
        id=row.id,
        entity_id=row.entity_id,
        tenant_id=row.tenant_id,
        flow_id=row.flow_id,
        category=RetentionCategory(row.category),
        state=ReceiptState(
            phase=ReceiptPhase(row.phase),
            paused_from=(
                ReceiptPhase(row.paused_from_phase)
                if row.paused_from_phase is not None
                else None
            ),
            reason=ReceiptReason(row.reason) if row.reason is not None else None,
        ),
        manifest_after=(
            ManifestPosition(
                file_id=row.manifest_after_file_id,
                variant=row.manifest_after_variant,
                ordinal=row.manifest_after_ordinal,
            )
            if row.manifest_after_file_id is not None
            and row.manifest_after_variant is not None
            and row.manifest_after_ordinal is not None
            else None
        ),
        files_deleted=row.files_deleted,
        manifest_complete=row.manifest_completed_at is not None,
        started_at=row.started_at,
        rows_deleted=row.rows_deleted,
        trigger=RetentionTrigger(row.trigger),
        source_run_id=row.source_run_id,
    )


def _phase_values(phases: frozenset[ReceiptPhase]) -> list[str]:
    return [phase.value for phase in phases]


# A receipt being pruned no longer covers its entity: it is never continued,
# reopened or physically confirmed.
_NOT_PRUNING = RetentionReceipts.pruning_started_at.is_(None)


class RetentionReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open(self, receipt: NewRetentionReceipt) -> RetentionReceipt:
        """Insert the receipt or return the existing one, locked for this chunk."""
        now = sa.func.clock_timestamp()
        await self.session.execute(
            pg_insert(RetentionReceipts)
            .values(
                task=receipt.task,
                entity_kind=receipt.entity_kind.value,
                entity_id=receipt.entity_id,
                category=receipt.category.value,
                trigger=receipt.trigger.value,
                tenant_id=receipt.tenant_id,
                space_id=receipt.space_id,
                flow_id=receipt.flow_id,
                source_run_id=receipt.source_run_id,
                policy_source=(
                    receipt.policy_source.value
                    if receipt.policy_source is not None
                    else None
                ),
                policy_days=receipt.policy_days,
                policy_scope_id=receipt.policy_scope_id,
                policy_mode=receipt.policy_mode,
                triggered_by_user_id=receipt.triggered_by_user_id,
                anchor_at=receipt.anchor_at,
                due_at=receipt.due_at,
                phase=ReceiptPhase.PENDING.value,
                started_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    RetentionReceipts.task,
                    RetentionReceipts.entity_kind,
                    RetentionReceipts.entity_id,
                    RetentionReceipts.category,
                ],
                # A literal predicate: the partial index is inferred at plan time.
                index_where=sa.text("pruning_started_at IS NULL"),
            )
        )
        row = await self.session.scalar(
            sa.select(RetentionReceipts)
            .where(
                RetentionReceipts.task == receipt.task,
                RetentionReceipts.entity_kind == receipt.entity_kind.value,
                RetentionReceipts.entity_id == receipt.entity_id,
                RetentionReceipts.category == receipt.category.value,
                _NOT_PRUNING,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("Retention receipt vanished while it was opened.")
        return _receipt(row)

    async def lock(self, receipt_id: UUID) -> RetentionReceipt | None:
        """The receipt, locked for this chunk; None once it is gone or pruning."""
        row = await self.session.scalar(
            sa.select(RetentionReceipts)
            .where(RetentionReceipts.id == receipt_id, _NOT_PRUNING)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return _receipt(row) if row is not None else None

    async def unfinished(
        self,
        *,
        task: str,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[RetentionReceipt]:
        """Unfinished receipts after a keyset position; rows another chunk holds are skipped."""
        stmt = (
            sa.select(RetentionReceipts)
            .where(
                RetentionReceipts.task == task,
                RetentionReceipts.phase.in_(_phase_values(NON_FINAL_RECEIPT_PHASES)),
                _NOT_PRUNING,
            )
            .order_by(RetentionReceipts.started_at, RetentionReceipts.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if after is not None:
            stmt = stmt.where(
                sa.tuple_(RetentionReceipts.started_at, RetentionReceipts.id)
                > sa.tuple_(sa.literal(after[0]), sa.literal(after[1]))
            )
        return [_receipt(row) for row in await self.session.scalars(stmt)]

    async def save(self, receipt_id: UUID, update: ReceiptUpdate) -> None:
        now = sa.func.clock_timestamp()
        state = update.state
        after = update.manifest_after
        values: dict[str, Any] = {
            "phase": state.phase.value,
            "paused_from_phase": (
                state.paused_from.value if state.paused_from is not None else None
            ),
            "reason": state.reason.value if state.reason is not None else None,
            "manifest_after_file_id": after.file_id if after else None,
            "manifest_after_variant": after.variant if after else None,
            "manifest_after_ordinal": after.ordinal if after else None,
            "files_deleted": update.files_deleted,
            "rows_deleted": update.rows_deleted,
            "chunk_count": RetentionReceipts.chunk_count + 1,
            "updated_at": now,
        }
        if update.manifest_complete:
            values["manifest_completed_at"] = sa.func.coalesce(
                RetentionReceipts.manifest_completed_at, now
            )
        if state.is_final:
            values["completed_at"] = now
        await self.session.execute(
            sa.update(RetentionReceipts)
            .where(RetentionReceipts.id == receipt_id)
            .values(**values)
        )

    async def withdraw(self, receipt_id: UUID) -> None:
        """Mark a receipt that released nothing for pruning; one row, its manifest
        is deleted by the bounded pruning."""
        await self.session.execute(
            sa.update(RetentionReceipts)
            .where(
                RetentionReceipts.id == receipt_id,
                RetentionReceipts.phase == ReceiptPhase.PENDING.value,
                _NOT_PRUNING,
            )
            .values(pruning_started_at=sa.func.clock_timestamp())
        )

    async def append_items(
        self, receipt_id: UUID, pairs: Sequence[tuple[UUID, UUID]]
    ) -> None:
        if not pairs:
            return
        await self.session.execute(
            sa.insert(RetentionReceiptItems),
            [
                {"receipt_id": receipt_id, "file_id": file_id, "content_id": content_id}
                for file_id, content_id in pairs
            ],
        )

    async def physical_pending(
        self, *, start: RetentionKeyset | None, inclusive: bool, limit: int
    ) -> list[PhysicalReceiptKey]:
        """Completed receipts (manifest enumerated, empty included) not yet confirmed,
        in (completed_at, id) order from `start`."""
        stmt = (
            sa.select(
                RetentionReceipts.completed_at,
                RetentionReceipts.id,
                RetentionReceipts.tenant_id,
            )
            .where(
                RetentionReceipts.phase == ReceiptPhase.COMPLETED.value,
                RetentionReceipts.manifest_completed_at.is_not(None),
                RetentionReceipts.physical_confirmed_at.is_(None),
                _NOT_PRUNING,
            )
            .order_by(RetentionReceipts.completed_at, RetentionReceipts.id)
            .limit(limit)
        )
        if start is not None:
            key = sa.tuple_(RetentionReceipts.completed_at, RetentionReceipts.id)
            bound = sa.tuple_(sa.literal(start.at), sa.literal(start.id))
            stmt = stmt.where(key >= bound if inclusive else key > bound)
        rows = await self.session.execute(stmt)
        return [
            PhysicalReceiptKey(
                completed_at=completed_at, id=receipt_id, tenant_id=tenant_id
            )
            for completed_at, receipt_id, tenant_id in rows.tuples()
            if completed_at is not None
        ]

    async def confirm_items(
        self, receipt_id: UUID, *, after_item: int | None, limit: int
    ) -> PhysicalItemPage:
        """Record what the content owner reports for the next unconfirmed items.

        Confirmed means the content row is gone or tombstoned (deleted) or another
        reference still holds it (shared); anything else stays pending and is
        looked at again in a later execution.
        """
        page_stmt = (
            sa.select(RetentionReceiptItems.id)
            .where(
                RetentionReceiptItems.receipt_id == receipt_id,
                RetentionReceiptItems.confirmed_at.is_(None),
            )
            .order_by(RetentionReceiptItems.id)
            .limit(limit)
        )
        if after_item is not None:
            page_stmt = page_stmt.where(RetentionReceiptItems.id > after_item)
        item_ids = list(await self.session.scalars(page_stmt))
        if not item_ids:
            return PhysicalItemPage(examined=0, last_item=after_item, finished=True)
        content = aliased(ObjectContents)
        disposition = sa.case(
            (
                sa.or_(
                    content.id.is_(None),
                    content.state == ContentState.TOMBSTONED.value,
                ),
                ReceiptItemDisposition.DELETED.value,
            ),
            (content.reference_count > 0, ReceiptItemDisposition.SHARED.value),
            else_=None,
        )
        resolved = (
            sa.select(RetentionReceiptItems.id.label("item_id"), disposition.label("d"))
            .outerjoin(content, content.id == RetentionReceiptItems.content_id)
            .where(
                RetentionReceiptItems.id
                == sa.any_(sa.literal(item_ids, type_=ARRAY(sa.BigInteger)))
            )
            .subquery()
        )
        await self.session.execute(
            sa.update(RetentionReceiptItems)
            .where(RetentionReceiptItems.id == resolved.c.item_id)
            .where(resolved.c.d.is_not(None))
            .values(disposition=resolved.c.d, confirmed_at=sa.func.clock_timestamp())
        )
        return PhysicalItemPage(
            examined=len(item_ids),
            last_item=item_ids[-1],
            finished=len(item_ids) < limit,
        )

    async def has_unconfirmed_items(self, receipt_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.select(sa.literal(1))
                    .select_from(RetentionReceiptItems)
                    .where(
                        RetentionReceiptItems.receipt_id == receipt_id,
                        RetentionReceiptItems.confirmed_at.is_(None),
                    )
                    .exists()
                )
            )
        )

    async def mark_physically_confirmed(self, receipt_id: UUID) -> None:
        await self.session.execute(
            sa.update(RetentionReceipts)
            .where(
                RetentionReceipts.id == receipt_id,
                RetentionReceipts.phase == ReceiptPhase.COMPLETED.value,
                RetentionReceipts.manifest_completed_at.is_not(None),
                _NOT_PRUNING,
            )
            .values(physical_confirmed_at=sa.func.clock_timestamp())
        )

    async def prune(
        self, *, limit: int, held: sa.ColumnElement[bool] | None = None
    ) -> PrunedReceipts:
        """Write at most `limit` rows of receipt pruning; resumable across calls.

        Receipts already marked are continued first, oldest mark first: their
        manifest items are deleted in bounded batches, and a receipt is deleted
        once it has no item left. The rest of the budget marks final receipts
        older than the deployment's audit retention (one literal cutoff bounds
        the index range scan); unfinished receipts are only pruned when they were
        withdrawn. Receipts matching `held` (the adopter's legal hold predicate
        over the receipt's columns) are skipped in both stages. Rows another
        chunk holds are skipped.
        """
        left = limit
        kept = sa.not_(held) if held is not None else sa.true()
        marked = (
            await self.session.execute(
                sa.select(RetentionReceipts.id, RetentionReceipts.tenant_id)
                .where(RetentionReceipts.pruning_started_at.is_not(None), kept)
                .order_by(RetentionReceipts.pruning_started_at, RetentionReceipts.id)
                .limit(left)
                .with_for_update(skip_locked=True)
            )
        ).tuples()
        items_deleted: dict[UUID, int] = {}
        emptied: list[UUID] = []
        for receipt_id, tenant_id in marked:
            if left == 0:
                break
            items = await self._delete_items(receipt_id, limit=left)
            left -= items
            if items:
                items_deleted[tenant_id] = items_deleted.get(tenant_id, 0) + items
            if left > 0:
                # Fewer items than the budget allowed: none is left.
                emptied.append(receipt_id)
                left -= 1
        pruned: list[tuple[UUID, UUID]] = []
        if emptied:
            rows = await self.session.execute(
                sa.delete(RetentionReceipts)
                .where(uuid_in(RetentionReceipts.id, emptied))
                .returning(RetentionReceipts.id, RetentionReceipts.tenant_id)
            )
            pruned = [
                (receipt_id, tenant_id) for receipt_id, tenant_id in rows.tuples()
            ]
        marks: dict[UUID, int] = {}
        if left > 0:
            for tenant_id in await self._mark_expired(limit=left, kept=kept):
                marks[tenant_id] = marks.get(tenant_id, 0) + 1
                left -= 1
        return PrunedReceipts(
            rows=limit - left,
            receipts=tuple(pruned),
            items_deleted=items_deleted,
            receipts_marked=marks,
        )

    async def _delete_items(self, receipt_id: UUID, *, limit: int) -> int:
        item_ids = list(
            await self.session.scalars(
                sa.select(RetentionReceiptItems.id)
                .where(RetentionReceiptItems.receipt_id == receipt_id)
                .order_by(RetentionReceiptItems.id)
                .limit(limit)
            )
        )
        if not item_ids:
            return 0
        await self.session.execute(
            sa.delete(RetentionReceiptItems).where(
                RetentionReceiptItems.id
                == sa.any_(sa.literal(item_ids, type_=ARRAY(sa.BigInteger)))
            )
        )
        return len(item_ids)

    async def _mark_expired(
        self, *, limit: int, kept: sa.ColumnElement[bool]
    ) -> list[UUID]:
        """Mark expired final receipts; the tenant of each one marked."""
        # now() is stable, so the cutoff is an index bound (clock_timestamp() is not).
        cutoff = sa.func.now() - sa.func.make_interval(
            0, 0, 0, deployment_audit_retention_days()
        )
        ids = list(
            await self.session.scalars(
                sa.select(RetentionReceipts.id)
                .where(
                    RetentionReceipts.phase.in_(_phase_values(FINAL_RECEIPT_PHASES)),
                    RetentionReceipts.completed_at < cutoff,
                    _NOT_PRUNING,
                    kept,
                )
                .order_by(RetentionReceipts.completed_at, RetentionReceipts.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        if not ids:
            return []
        return list(
            await self.session.scalars(
                sa.update(RetentionReceipts)
                .where(uuid_in(RetentionReceipts.id, ids))
                .values(pruning_started_at=sa.func.clock_timestamp())
                .returning(RetentionReceipts.tenant_id)
            )
        )
