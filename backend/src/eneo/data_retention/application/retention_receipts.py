"""Receipt (deletion evidence) rules: phase changes, manifests, physical confirmation.

A receipt records what a deletion releases before anything is released: the
manifest of (file, content) pairs is appended in bounded batches while the
receipt is pending, and the release step refuses until the manifest is complete.
Physical deletion is confirmed per item by the content owner's state, and a
receipt counts as physically confirmed only once its manifest enumeration
finished (an empty manifest included) and every item is confirmed; a receipt
whose pruning started is never confirmed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStepResult,
    RetentionTenantEffect,
)
from eneo.data_retention.domain.retention import (
    InvalidReceiptTransition,
    ManifestPosition,
    NewRetentionReceipt,
    PhysicalCursor,
    PhysicalItemPage,
    PhysicalReceiptKey,
    PrunedReceipts,
    ReceiptPhase,
    ReceiptReason,
    ReceiptState,
    ReceiptUpdate,
    RetentionKeyset,
    RetentionReceipt,
)

# The names receipt pruning reports; a task that registers prune_step declares them.
RECEIPT_PRUNING_COUNT_KEYS = frozenset(
    {"receipts_pruned", "items_pruned", "receipts_marked"}
)
# The names physical confirmation reports; a task that registers physical_step
# declares them.
PHYSICAL_CONFIRMATION_COUNT_KEYS = frozenset({"items_examined", "receipts_confirmed"})
PHYSICAL_CONFIRMATION_BLOCKED_KEYS = frozenset({"physical_pending"})


class RetentionReceiptStore(Protocol):
    async def open(self, receipt: NewRetentionReceipt) -> RetentionReceipt: ...

    async def lock(self, receipt_id: UUID) -> RetentionReceipt | None: ...

    async def unfinished(
        self, *, task: str, after: tuple[datetime, UUID] | None, limit: int
    ) -> list[RetentionReceipt]: ...

    async def prune(
        self, *, limit: int, held: sa.ColumnElement[bool] | None = None
    ) -> PrunedReceipts: ...

    async def save(self, receipt_id: UUID, update: ReceiptUpdate) -> None: ...

    async def withdraw(self, receipt_id: UUID) -> None: ...

    async def append_items(
        self, receipt_id: UUID, pairs: Sequence[tuple[UUID, UUID]]
    ) -> None: ...

    async def physical_pending(
        self, *, start: RetentionKeyset | None, inclusive: bool, limit: int
    ) -> list[PhysicalReceiptKey]: ...

    async def confirm_items(
        self, receipt_id: UUID, *, after_item: int | None, limit: int
    ) -> PhysicalItemPage: ...

    async def has_unconfirmed_items(self, receipt_id: UUID) -> bool: ...

    async def mark_physically_confirmed(self, receipt_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class PhysicalConfirmation:
    items_examined: int = 0
    receipts_examined: int = 0
    confirmed: tuple[PhysicalReceiptKey, ...] = ()


class RetentionReceiptService:
    def __init__(self, store: RetentionReceiptStore) -> None:
        self.store = store

    async def open(self, receipt: NewRetentionReceipt) -> RetentionReceipt:
        return await self.store.open(receipt)

    async def lock(self, receipt_id: UUID) -> RetentionReceipt | None:
        """A receipt this chunk continues, locked; None once it is gone."""
        return await self.store.lock(receipt_id)

    async def unfinished(
        self, *, task: str, after: tuple[datetime, UUID] | None, limit: int
    ) -> list[RetentionReceipt]:
        """Unfinished receipts of a task after a keyset position, locked."""
        return await self.store.unfinished(task=task, after=after, limit=limit)

    async def prune(
        self, *, limit: int, held: sa.ColumnElement[bool] | None = None
    ) -> PrunedReceipts:
        """Prune withdrawn receipts and final ones past the audit retention.

        Writes at most `limit` rows (marks, manifest items and receipts) and
        continues in the next call; a receipt is deleted only after its items,
        and receipts matching `held` are kept.
        """
        return await self.store.prune(limit=limit, held=held)

    async def prune_step(
        self, batch: RetentionBatch, *, held: sa.ColumnElement[bool] | None = None
    ) -> RetentionStepResult:
        """One runner call of receipt pruning; every row it wrote is an effect.

        The task declares RECEIPT_PRUNING_COUNT_KEYS. Receipts marked in a call
        are deleted by a later one, so the pass ends with a call that writes
        nothing.
        """
        pruned = await self.prune(limit=batch.rows, held=held)
        counts: dict[UUID, dict[str, int]] = {}
        for tenant_id, key, value in (
            *((tenant, "receipts_pruned", 1) for _, tenant in pruned.receipts),
            *(
                (tenant, "items_pruned", n)
                for tenant, n in pruned.items_deleted.items()
            ),
            *(
                (tenant, "receipts_marked", n)
                for tenant, n in pruned.receipts_marked.items()
            ),
        ):
            tenant_counts = counts.setdefault(tenant_id, {})
            tenant_counts[key] = tenant_counts.get(key, 0) + value
        receipt_ids: dict[UUID, list[UUID]] = {}
        for receipt_id, tenant_id in pruned.receipts:
            receipt_ids.setdefault(tenant_id, []).append(receipt_id)
        return RetentionStepResult(
            rows=pruned.rows,
            effects=tuple(
                RetentionTenantEffect(
                    tenant_id=tenant_id,
                    counts=tenant_counts,
                    receipt_ids=tuple(receipt_ids.get(tenant_id, ())),
                )
                for tenant_id, tenant_counts in counts.items()
            ),
            exhausted=pruned.rows == 0,
        )

    async def withdraw(self, receipt: RetentionReceipt) -> None:
        """Drop a receipt whose entity left the candidate set before any release.

        The receipt is marked at once and stops covering its entity; pruning
        deletes it and its partial manifest in bounded batches.
        """
        if receipt.state.phase != ReceiptPhase.PENDING:
            raise InvalidReceiptTransition("Only a pending receipt can be withdrawn.")
        await self.store.withdraw(receipt.id)

    async def append_manifest(
        self,
        receipt: RetentionReceipt,
        pairs: Sequence[tuple[UUID, UUID]],
        *,
        manifest_after: ManifestPosition | None,
        complete: bool,
    ) -> RetentionReceipt:
        if receipt.state.phase != ReceiptPhase.PENDING or receipt.manifest_complete:
            raise InvalidReceiptTransition("The manifest is closed once released.")
        await self.store.append_items(receipt.id, pairs)
        return await self._save(
            receipt,
            receipt.state,
            manifest_after=manifest_after,
            manifest_complete=complete,
        )

    async def release(self, receipt: RetentionReceipt) -> RetentionReceipt:
        """Mark the discovery anchor released; only after the complete manifest."""
        if not receipt.manifest_complete:
            raise InvalidReceiptTransition("Release needs the complete manifest first.")
        return await self._save(receipt, receipt.state.advance(ReceiptPhase.RELEASING))

    async def advance(
        self,
        receipt: RetentionReceipt,
        target: ReceiptPhase,
        *,
        files_deleted: int = 0,
        rows_deleted: int = 0,
    ) -> RetentionReceipt:
        return await self._save(
            receipt,
            receipt.state.advance(target),
            files_deleted=files_deleted,
            rows_deleted=rows_deleted,
        )

    async def record(
        self,
        receipt: RetentionReceipt,
        *,
        files_deleted: int = 0,
        rows_deleted: int = 0,
    ) -> RetentionReceipt:
        """Add a chunk's deletions without a phase change."""
        return await self._save(
            receipt,
            receipt.state,
            files_deleted=files_deleted,
            rows_deleted=rows_deleted,
        )

    async def pause(
        self, receipt: RetentionReceipt, reason: ReceiptReason
    ) -> RetentionReceipt:
        return await self._save(receipt, receipt.state.pause(reason))

    async def resume(self, receipt: RetentionReceipt) -> RetentionReceipt:
        return await self._save(receipt, receipt.state.resume())

    async def confirm_physical(
        self, *, budget: int, cursor: PhysicalCursor | None
    ) -> tuple[PhysicalConfirmation, PhysicalCursor | None]:
        """Examine completed, unconfirmed receipts within `budget` rows.

        Each manifest item examined counts one, and so does finishing a receipt
        (deciding whether it is confirmed), so every call with a budget makes
        progress. Continues from `cursor`; returns the cursor for the next
        call, or None once every pending receipt of this pass was examined.
        """
        used = 0
        examined = 0
        finished = 0
        confirmed: list[PhysicalReceiptKey] = []
        after_item = cursor.after_item if cursor is not None else None
        receipts = await self.store.physical_pending(
            start=cursor.receipt if cursor is not None else None,
            inclusive=after_item is not None,
            limit=budget,
        )
        last: PhysicalReceiptKey | None = None
        for key in receipts:
            while True:
                left = budget - used
                if left <= 0:
                    return (
                        PhysicalConfirmation(examined, finished, tuple(confirmed)),
                        PhysicalCursor(
                            receipt=RetentionKeyset(at=key.completed_at, id=key.id),
                            after_item=after_item or 0,
                        ),
                    )
                page = await self.store.confirm_items(
                    key.id, after_item=after_item, limit=left
                )
                examined += page.examined
                used += page.examined
                after_item = page.last_item
                if page.finished and used < budget:
                    break
            used += 1
            finished += 1
            if not await self.store.has_unconfirmed_items(key.id):
                await self.store.mark_physically_confirmed(key.id)
                confirmed.append(key)
            after_item = None
            last = key
        confirmation = PhysicalConfirmation(examined, finished, tuple(confirmed))
        if len(receipts) < budget or last is None:
            return confirmation, None
        return confirmation, PhysicalCursor(
            receipt=RetentionKeyset(at=last.completed_at, id=last.id)
        )

    async def physical_step(self, batch: RetentionBatch) -> RetentionStepResult:
        """One runner call of physical confirmation, from the durable cursor.

        The cursor keeps the receipt and the item position inside it, so a
        receipt with more items than one night's budget continues the next
        night where it stopped. The task declares PHYSICAL_CONFIRMATION_*_KEYS.
        """
        start = batch.cursor
        confirmation, cursor = await self.confirm_physical(
            budget=batch.rows,
            cursor=(
                PhysicalCursor(
                    receipt=RetentionKeyset(at=start.at, id=start.id),
                    after_item=start.item,
                )
                if start is not None
                else None
            ),
        )
        receipts: dict[UUID, list[UUID]] = {}
        for key in confirmation.confirmed:
            receipts.setdefault(key.tenant_id, []).append(key.id)
        # Item confirmations are bookkeeping of the deployment's proof.
        effects = [
            RetentionTenantEffect(
                tenant_id=None, counts={"items_examined": confirmation.items_examined}
            ),
            *(
                RetentionTenantEffect(
                    tenant_id=tenant_id,
                    counts={"receipts_confirmed": len(ids)},
                    receipt_ids=tuple(ids),
                )
                for tenant_id, ids in receipts.items()
            ),
        ]
        return RetentionStepResult(
            rows=confirmation.items_examined + confirmation.receipts_examined,
            effects=tuple(effects),
            # Examined receipts whose content is not all gone yet.
            blocked={
                "physical_pending": confirmation.receipts_examined
                - len(confirmation.confirmed)
            },
            exhausted=cursor is None,
            cursor=(
                RetentionKeyset(
                    at=cursor.receipt.at, id=cursor.receipt.id, item=cursor.after_item
                )
                if cursor is not None
                else None
            ),
        )

    async def _save(
        self,
        receipt: RetentionReceipt,
        state: ReceiptState,
        *,
        manifest_after: ManifestPosition | None = None,
        files_deleted: int = 0,
        manifest_complete: bool = False,
        rows_deleted: int = 0,
    ) -> RetentionReceipt:
        complete = receipt.manifest_complete or manifest_complete
        if state.phase == ReceiptPhase.COMPLETED and not complete:
            raise InvalidReceiptTransition("A receipt completes after its manifest.")
        update = ReceiptUpdate(
            state=state,
            manifest_after=manifest_after or receipt.manifest_after,
            files_deleted=receipt.files_deleted + files_deleted,
            manifest_complete=complete,
            rows_deleted=receipt.rows_deleted + rows_deleted,
        )
        await self.store.save(receipt.id, update)
        return replace(
            receipt,
            state=state,
            manifest_after=update.manifest_after,
            files_deleted=update.files_deleted,
            manifest_complete=complete,
            rows_deleted=update.rows_deleted,
        )
