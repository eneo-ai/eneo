"""The flows.housekeeping gallring task: staging and waste data, never run history.

Steps, in order (each call is one chunk of the runner):

1. file_families: receipts of families an earlier pass paused (an owner, the
   depth bound or the family cap), retried from the start;
2. abandoned_uploads: runtime uploads never attached to a run, past the current
   window, reclaimed as file families (the upload and every file derived from
   it);
3. live_transcripts: transcripts never bound to a run, past the current window;
4. audit_outbox: delivered mirrors past the audit retention whose audit log
   entry is gone;
5. physical_confirmation, 6. prune_receipts, 7. prune_job_runs.

A family is reclaimed atomically, in one transaction: measured within the
family cap, every member locked and checked afresh for another owner, the depth
bound checked, the complete manifest written, the binding and the bound live
transcripts released, the members deleted deepest first and the receipt
completed; or the receipt is paused with its reason. Nothing about a family is
kept between transactions. A family that does not fit what is left of the
night's budget ends its step for the night with the step's durable cursor
before it; one larger than the family cap is paused (family_exceeds_budget).

Every chunk first takes the flow history gallring lock SHARED, so a legal hold
or policy change and a chunk never overlap. No step deletes data an active hold
covers (flow_run_held_predicate: a Flow hold covers all of the flow's data, a run
hold the run's outbox mirrors); such rows are skipped and counted as held, and
receipt pruning keeps the receipts of held Flows.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_receipts import (
    PHYSICAL_CONFIRMATION_BLOCKED_KEYS,
    PHYSICAL_CONFIRMATION_COUNT_KEYS,
    RECEIPT_PRUNING_COUNT_KEYS,
    RetentionReceiptService,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import (
    NewRetentionReceipt,
    ReceiptPhase,
    ReceiptReason,
    RetentionCategory,
    RetentionEntityKind,
    RetentionKeyset,
    RetentionReceipt,
)
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.data_retention.infrastructure.retention_receipt_repo import (
    RetentionReceiptRepository,
)
from eneo.flows.infrastructure.flow_file_family_repo import (
    UPLOAD_ANCHOR_EDGES,
    FamilyBlock,
    FlowFileFamilyRepository,
)
from eneo.flows.infrastructure.flow_housekeeping_repo import (
    AbandonedUpload,
    FlowHousekeepingRepository,
)
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.main.config import get_settings

FLOWS_HOUSEKEEPING_TASK = "flows.housekeeping"

_COUNT_KEYS = frozenset(
    {
        "anchors_released",
        "files_deleted",
        "references_released",
        "manifest_items",
        "families_completed",
        "members_checked",
        "receipts_withdrawn",
        "transcripts_deleted",
        "outbox_rows_deleted",
        "job_runs_pruned",
        *PHYSICAL_CONFIRMATION_COUNT_KEYS,
        *RECEIPT_PRUNING_COUNT_KEYS,
    }
)
_BLOCKED_KEYS = frozenset(
    {
        "held",
        "lock_deferred",
        "recorded",
        "audit_log_retained",
        *PHYSICAL_CONFIRMATION_BLOCKED_KEYS,
        *(reason.value for reason in ReceiptReason),
    }
)


def _block_reason(block: FamilyBlock) -> ReceiptReason:
    if block.depth_exceeded:
        return ReceiptReason.FAMILY_DEPTH_EXCEEDED
    if block.is_root:
        return ReceiptReason.FILE_REFERENCED_ELSEWHERE
    return ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FlowHousekeepingTask:
    """flows.housekeeping; pass positions live on the job row, nothing else is
    kept between transactions."""

    count_keys = _COUNT_KEYS
    blocked_keys = _BLOCKED_KEYS

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] = _utcnow,
        family_rows: int | None = None,
        chunk_rows: int | None = None,
    ) -> None:
        settings = get_settings()
        self._now = now
        self._family_rows = (
            family_rows
            if family_rows is not None
            else settings.gallring_max_family_rows
        )
        self._chunk_rows = (
            chunk_rows if chunk_rows is not None else settings.gallring_chunk_rows
        )
        self._gather_seconds = settings.gallring_family_gather_seconds
        self._receipts = RetentionReceiptService(RetentionReceiptRepository(session))
        self._job_runs = RetentionJobRunRepository(session)
        self._families = FlowFileFamilyRepository(session)
        self._housekeeping = FlowHousekeepingRepository(session)
        self._transcripts = LiveTranscriptRepository(session)

    @property
    def name(self) -> str:
        return FLOWS_HOUSEKEEPING_TASK

    def steps(self) -> Sequence[RetentionStep]:
        family = self._family_rows
        families = [
            ("file_families", self._file_families, family),
            ("abandoned_uploads", self._abandoned_uploads, family),
        ]
        # Consecutive execution dates alternate which family step sees the full
        # budget first. Backlog within either step still controls how soon a
        # particular family can be reclaimed.
        if self._now().date().toordinal() % 2:
            families.reverse()
        return tuple(
            RetentionStep(name, self._after_flow_history_lock(run), max_batch=batch)
            for name, run, batch in (
                *families,
                ("live_transcripts", self._live_transcripts, None),
                ("audit_outbox", self._audit_outbox, None),
                ("physical_confirmation", self._receipts.physical_step, None),
                ("prune_receipts", self._prune_receipts, None),
                ("prune_job_runs", self._prune_job_runs, None),
            )
        )

    def _after_flow_history_lock(
        self, run: Callable[[RetentionBatch], Awaitable[RetentionStepResult]]
    ) -> Callable[[RetentionBatch], Awaitable[RetentionStepResult]]:
        async def locked(batch: RetentionBatch) -> RetentionStepResult:
            # Before any selection: holds are read as they are at deletion.
            await self._housekeeping.lock_flow_history()
            return await run(batch)

        return locked

    # Families ---------------------------------------------------------------

    async def _file_families(self, batch: RetentionBatch) -> RetentionStepResult:
        """Paused receipts, oldest first, one at a time from the durable cursor."""
        out = RetentionEffects()

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            receipts = await self._receipts.unfinished(
                task=FLOWS_HOUSEKEEPING_TASK,
                after=(after.at, after.id) if after is not None else None,
                limit=1,
            )
            if not receipts:
                return None
            receipt = receipts[0]

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                if receipt.flow_id is not None and await self._held({receipt.flow_id}):
                    out.blocked["held"] += 1
                    return RetentionUnitUsage(rows=1, files=0)
                return await self._reclaim(
                    receipt.entity_id,
                    receipt=receipt,
                    rows=rows,
                    files=files,
                    out=out,
                )

            return RetentionKeyset(at=receipt.started_at, id=receipt.id), handle

        return await gather_retention_units(
            batch,
            next_candidate,
            out,
            chunk_rows=self._chunk_rows,
            gather_seconds=self._gather_seconds,
            clock=time.monotonic,
        )

    async def _abandoned_uploads(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            uploads = await self._housekeeping.abandoned_uploads(
                now=self._now(), after=after, limit=1
            )
            if not uploads:
                return None
            upload = uploads[0]

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                if await self._housekeeping.recorded_families(
                    task=FLOWS_HOUSEKEEPING_TASK,
                    category=RetentionCategory.ABANDONED_UPLOAD,
                    root_ids=[upload.file_id],
                ):
                    out.blocked["recorded"] += 1  # the file_families step owns it
                    return RetentionUnitUsage(rows=1, files=0)
                if await self._held({upload.flow_id}):
                    out.blocked["held"] += 1
                    return RetentionUnitUsage(rows=1, files=0)
                return await self._reclaim(
                    upload.file_id,
                    upload=upload,
                    rows=rows,
                    files=files,
                    out=out,
                )

            return RetentionKeyset(at=upload.created_at, id=upload.file_id), handle

        return await gather_retention_units(
            batch,
            next_candidate,
            out,
            chunk_rows=self._chunk_rows,
            gather_seconds=self._gather_seconds,
            clock=time.monotonic,
        )

    async def _reclaim(
        self,
        root: UUID,
        *,
        rows: int,
        files: int,
        out: RetentionEffects,
        receipt: RetentionReceipt | None = None,
        upload: AbandonedUpload | None = None,
    ) -> RetentionUnitUsage:
        """Reclaim one family atomically, or pause its receipt with the reason.

        `rows` (examined) and `files` (deleted or recorded) are what this
        candidate may charge. A family costs rows 2 + 4m + 2r + 2t (the
        candidate and the depth check; each member counted, enumerated, enumerated
        again under its lock and checked; each content reference and bound live
        transcript counted and listed) and files 1 + m + 2r + t (the binding,
        file rows, manifest items, released references, transcripts). Every
        retrieval is bounded before it materializes anything, and every row it
        examines is charged. Over the cap the receipt is paused; within it, a
        family that does not fit what is left waits for a call of its own, or
        for tomorrow when even a fresh call cannot hold it.
        """
        now = self._now()
        if receipt is not None and not await self._housekeeping.upload_eligible(
            root, now=now
        ):
            await self._receipts.withdraw(receipt)
            out.add(receipt.tenant_id, "receipts_withdrawn")
            return RetentionUnitUsage(rows=1, files=0)
        if not await self._housekeeping.lock_upload(root, now=now):
            out.blocked["lock_deferred"] += 1
            return RetentionUnitUsage(rows=1, files=0)
        cap = self._family_rows
        not_now = RetentionUnitDisposition.DOES_NOT_FIT
        used = 1
        if rows <= used:
            return RetentionUnitUsage(rows=used, files=0, disposition=not_now)

        def room(most: int) -> int:
            # A count may examine `most` + 1 rows (the sentinel) within what is left.
            return max(0, min(most, rows - used - 1))

        member_max = (cap - 2) // 4
        limit = room(member_max)
        members = await self._families.count_members(root, limit=limit + 1)
        used += members
        if members > member_max:
            return await self._over_cap(root, receipt, upload, used, out)
        if members > limit:
            return RetentionUnitUsage(rows=used, files=0, disposition=not_now)
        reference_max = (cap - 2 - 4 * members) // 2
        limit = room(reference_max)
        references = await self._families.count_references(root, limit=limit + 1)
        used += references
        if references > reference_max:
            return await self._over_cap(root, receipt, upload, used, out)
        if references > limit:
            return RetentionUnitUsage(rows=used, files=0, disposition=not_now)
        transcript_max = (cap - 2 - 4 * members - 2 * references) // 2
        limit = room(transcript_max)
        transcripts = await self._families.count_bound_transcripts(
            root, limit=limit + 1
        )
        used += transcripts
        if transcripts > transcript_max:
            return await self._over_cap(root, receipt, upload, used, out)
        if (
            transcripts > limit
            or 2 + 4 * members + 2 * references + 2 * transcripts > rows
            or 1 + members + 2 * references + transcripts > files
        ):
            return RetentionUnitUsage(rows=used, files=0, disposition=not_now)

        # Under the locks the family is read again, never past what was counted:
        # anything that grew in between makes it wait for another pass.
        locked = await self._families.lock_members(root, limit=members)
        used += locked.examined
        if locked.items is None:
            out.blocked["lock_deferred"] += 1
            return RetentionUnitUsage(rows=used, files=0)
        manifest = await self._families.manifest(locked.items, limit=references)
        used += manifest.examined
        bound = await self._families.count_all_bound_transcripts(
            root, limit=transcripts
        )
        used += bound
        if manifest.items is None or bound > transcripts:
            out.blocked["lock_deferred"] += 1
            return RetentionUnitUsage(rows=used, files=0)
        members_locked, pairs = locked.items, manifest.items
        receipt = await self._receipt(root, receipt, upload)
        tenant_id = receipt.tenant_id
        out.add(tenant_id, "members_checked", len(members_locked))
        used += len(members_locked) + 1
        block = await self._families.outside_owner(
            root, members_locked, root_anchor_edges=UPLOAD_ANCHOR_EDGES
        ) or await self._families.too_deep(root)
        if block is not None:
            await self._pause(receipt, _block_reason(block), out)
            return RetentionUnitUsage(rows=used, files=0)
        receipt = await self._receipts.append_manifest(
            receipt, pairs, manifest_after=None, complete=True
        )
        released = await self._housekeeping.release_upload_binding(root)
        receipt = await self._receipts.release(receipt)
        deleted_transcripts = await self._housekeeping.release_bound_transcripts(root)
        receipt = await self._receipts.advance(receipt, ReceiptPhase.DELETING)
        deleted = await self._families.delete_members(members_locked)
        await self._receipts.advance(
            receipt, ReceiptPhase.COMPLETED, files_deleted=deleted
        )
        for key, value in (
            ("manifest_items", len(pairs)),
            ("anchors_released", released),
            ("transcripts_deleted", deleted_transcripts),
            ("references_released", len(pairs)),
            ("files_deleted", deleted),
            ("families_completed", 1),
        ):
            out.add(tenant_id, key, value)
        out.receipts[tenant_id].append(receipt.id)
        return RetentionUnitUsage(
            rows=used,
            files=2 * len(pairs) + deleted + released + deleted_transcripts,
        )

    async def _over_cap(
        self,
        root: UUID,
        receipt: RetentionReceipt | None,
        upload: AbandonedUpload | None,
        used: int,
        out: RetentionEffects,
    ) -> RetentionUnitUsage:
        """Larger than the family cap: never reclaimed, paused once a pass."""
        receipt = await self._receipt(root, receipt, upload)
        await self._pause(receipt, ReceiptReason.FAMILY_EXCEEDS_BUDGET, out)
        return RetentionUnitUsage(rows=used, files=0)

    async def _receipt(
        self,
        root: UUID,
        receipt: RetentionReceipt | None,
        upload: AbandonedUpload | None,
    ) -> RetentionReceipt:
        """The family's receipt, open (pending) for this transaction."""
        if receipt is None:
            assert upload is not None
            policy = await self._housekeeping.abandonment_policy()
            receipt = await self._receipts.open(
                NewRetentionReceipt(
                    task=FLOWS_HOUSEKEEPING_TASK,
                    entity_kind=RetentionEntityKind.FILE_FAMILY,
                    entity_id=root,
                    category=RetentionCategory.ABANDONED_UPLOAD,
                    tenant_id=upload.tenant_id,
                    flow_id=upload.flow_id,
                    policy_source=policy.source,
                    policy_days=policy.days,
                    anchor_at=upload.created_at,
                )
            )
        if receipt.state.phase == ReceiptPhase.PAUSED:
            receipt = await self._receipts.resume(receipt)
        return receipt

    async def _pause(
        self, receipt: RetentionReceipt, reason: ReceiptReason, out: RetentionEffects
    ) -> None:
        await self._receipts.pause(receipt, reason)
        out.blocked[reason.value] += 1

    # Live transcripts never bound to a run -----------------------------------

    async def _live_transcripts(self, batch: RetentionBatch) -> RetentionStepResult:
        now = self._now()
        page = await self._transcripts.expired_unbound_page(
            now=now, after=batch.cursor, limit=batch.rows
        )
        held = await self._held({row.flow_id for row in page})
        deleted = await self._transcripts.delete_expired_unbound_ids(
            [row.id for row in page if row.flow_id not in held], now=now
        )
        out = RetentionEffects()
        out.add_rows(deleted, "transcripts_deleted")
        out.blocked["held"] += sum(1 for row in page if row.flow_id in held)
        return out.result(
            rows=len(page),
            exhausted=len(page) < batch.rows,
            cursor=(
                RetentionKeyset(at=page[-1].created_at, id=page[-1].id)
                if page
                else batch.cursor
            ),
        )

    # Delivered audit outbox mirrors -------------------------------------------

    async def _audit_outbox(self, batch: RetentionBatch) -> RetentionStepResult:
        page = await self._housekeeping.deletable_audit_outbox(
            now=self._now(), after=batch.cursor, limit=batch.rows
        )
        deleted = await self._housekeeping.delete_delivered_audit_outbox(
            [row.id for row in page if not row.held]
        )
        out = RetentionEffects()
        out.add_rows(deleted, "outbox_rows_deleted")
        held_rows = sum(1 for row in page if row.held)
        out.blocked["held"] += held_rows
        # An audit log written back between selection and deletion keeps its row.
        out.blocked["audit_log_retained"] += len(page) - held_rows - len(deleted)
        return out.result(
            rows=len(page),
            exhausted=len(page) < batch.rows,
            cursor=(
                RetentionKeyset(at=page[-1].delivered_at, id=page[-1].id)
                if page
                else batch.cursor
            ),
        )

    # Physical confirmation, pruning --------------------------------------------

    async def _prune_receipts(self, batch: RetentionBatch) -> RetentionStepResult:
        # A held Flow's receipts keep their proof, in both pruning stages.
        return await self._receipts.prune_step(
            batch, held=self._housekeeping.receipt_held()
        )

    async def _prune_job_runs(self, batch: RetentionBatch) -> RetentionStepResult:
        pruned = await self._job_runs.prune_after_audit_retention(limit=batch.rows)
        out = RetentionEffects()
        # Job runs belong to the deployment, not to a tenant's row.
        out.add(None, "job_runs_pruned", pruned)
        return out.result(rows=pruned, exhausted=pruned < batch.rows)

    # Shared -----------------------------------------------------------------------

    async def _held(self, flow_ids: set[UUID]) -> set[UUID]:
        return await self._housekeeping.held_flows(flow_ids)
