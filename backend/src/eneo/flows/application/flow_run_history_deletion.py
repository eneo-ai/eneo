"""Delete Flow run history through the shared retention engine.

Implements scheduled auto_delete and explicit preserve/auto_delete deletion.
Every transaction that calls it takes
the flow history retention lock SHARED first (`lock`), before any selection, so
a legal hold or policy change and a deletion never overlap.

One receipt per run (task flows.history, entity flow_run, category run_record)
carries the work across transactions:

- Admission locks the selected run and checks it on the locked row (terminal,
  no active hold, no undelivered audit event, no pending webhook delivery,
  every file root has stored content), opens the receipt and fences the run
  (FlowRuns.retention_receipt_id) in the same transaction. The fence releases
  nothing; from its commit the run reads as deleted.
- PENDING: the run's file families, one per transaction step, each settled
  atomically: measured within the family cap, every member locked, the family's
  (file, content) pairs recorded before this run's links are dropped, then each
  member checked afresh for another owner. The family is either kept
  (another owner: shared, never holding the run back) or reclaimed (binding and
  bound live transcripts released, members deleted deepest first). When the
  run links no file any more the manifest is closed: RELEASING.
- RELEASING: the run's child rows in bounded batches in foreign-key order, the
  run row last; then DELETING and COMPLETED in the same transaction.

Once fenced, only an active legal hold pauses the work (reason legal_hold; it
resumes on release); a later policy change does not. A family larger than the
family cap pauses it (family_exceeds_budget) until the operator raises
RETENTION_MAX_FAMILY_ROWS; one nested deeper than the traversal bound pauses it
(family_depth_exceeded). Examined rows and deleted child rows count against the
row budget; manifest items, released references, file rows, bindings and bound
transcripts against the file budget.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_receipts import RetentionReceiptService
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
)
from eneo.data_retention.domain.retention import (
    InvalidReceiptTransition,
    NewRetentionReceipt,
    ReceiptPhase,
    ReceiptReason,
    RetentionCategory,
    RetentionEntityKind,
    RetentionKeyset,
    RetentionReceipt,
    RetentionTrigger,
)
from eneo.data_retention.infrastructure.retention_lock import (
    RetentionSubject,
    acquire_shared,
)
from eneo.data_retention.infrastructure.retention_receipt_repo import (
    RetentionReceiptRepository,
)
from eneo.flows.application.flow_file_family_preparation import (
    FileFamilyPreparationStopped,
    prepare_file_family,
)
from eneo.flows.domain.flow_run_retention_policy import (
    FLOWS_HISTORY_TASK,
    FlowRunRetentionMode,
)
from eneo.flows.infrastructure.flow_file_family_repo import (
    UPLOAD_ANCHOR_EDGES,
    FamilyBlock,
    FamilyChangedUnderLock,
    FlowFileFamilyRepository,
)
from eneo.flows.infrastructure.flow_housekeeping_repo import FlowHousekeepingRepository
from eneo.flows.infrastructure.flow_run_deletion_repo import (
    DueRun,
    FlowRunDeletionRepository,
    RunBlockers,
)
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FlowHistoryRule,
    FlowRunHistoryDueRepository,
)
from eneo.main.config import get_settings

# What the nightly task and the explicit purge admit.
SCHEDULED_MODES = (FlowRunRetentionMode.AUTO_DELETE,)
EXPLICIT_MODES = (FlowRunRetentionMode.PRESERVE, FlowRunRetentionMode.AUTO_DELETE)


class FlowsHistoryCount(StrEnum):
    """What flows.history and the explicit purge count (audited per tenant)."""

    RUNS_ADMITTED = "runs_admitted"
    MANIFEST_ITEMS = "manifest_items"
    CHILD_ROWS_DELETED = "child_rows_deleted"
    RUNS_DELETED = "runs_deleted"
    TRANSCRIPTS_DELETED = "transcripts_deleted"
    BINDINGS_RELEASED = "bindings_released"
    FILES_DELETED = "files_deleted"
    REFERENCES_RELEASED = "references_released"
    RECEIPTS_COMPLETED = "receipts_completed"
    RECEIPTS_RESUMED = "receipts_resumed"
    FLOWS_EXAMINED = "flows_examined"
    RUNS_EXAMINED = "runs_examined"
    RECEIPTS_EXAMINED = "receipts_examined"


class RunBlock(StrEnum):
    """Why a run is passed or kept, besides a receipt pause reason."""

    HELD = "held"
    NOT_TERMINAL = "not_terminal"
    LOCK_DEFERRED = "lock_deferred"
    NOT_DUE = "not_due"
    ALREADY_ADMITTED = "already_admitted"
    FILE_WITHOUT_CONTENT = "file_without_content"
    SHARED = "shared"


BlockedKey = RunBlock | ReceiptReason
FLOWS_HISTORY_COUNT_KEYS = frozenset(FlowsHistoryCount)
FLOWS_HISTORY_BLOCKED_KEYS: frozenset[BlockedKey] = frozenset(
    {*RunBlock, *ReceiptReason}
)


def _delivery_reason(blockers: RunBlockers) -> ReceiptReason:
    if blockers.undelivered_audit:
        return ReceiptReason.UNDELIVERED_AUDIT
    return ReceiptReason.UNRESOLVED_WEBHOOK


def _blocked_reason(blockers: RunBlockers) -> BlockedKey:
    if blockers.held:
        return RunBlock.HELD
    if not blockers.terminal:
        return RunBlock.NOT_TERMINAL
    return _delivery_reason(blockers)


def due_blocked_reason(due: DueRun) -> BlockedKey | None:
    """Why a due candidate is passed at selection; None if it may be admitted."""
    if due.held:
        return RunBlock.HELD
    if due.undelivered_audit:
        return ReceiptReason.UNDELIVERED_AUDIT
    if due.unresolved_webhook:
        return ReceiptReason.UNRESOLVED_WEBHOOK
    return None


# Discovery returns a rule and a run; admission also reads the locked run,
# blockers, content predicate and opened receipt. Resume reserves its receipt,
# hold, run, blockers, root, binding and one bounded count sentinel.
RUN_ADMISSION_ROWS = 6
RUN_RESUME_ROWS = 8
FLOW_HISTORY_END = datetime.max.replace(tzinfo=timezone.utc)
FLOW_HISTORY_LAST_ID = UUID(int=(1 << 128) - 1)


@dataclass(frozen=True, slots=True)
class RunDeletionProgress:
    usage: RetentionUnitUsage
    receipt: RetentionReceipt | None


def _record(
    out: RetentionEffects,
    receipt: RetentionReceipt,
    key: FlowsHistoryCount,
    value: int = 1,
) -> None:
    if value:
        out.add(receipt.tenant_id, key.value, value)
        out.receipts[receipt.tenant_id].append(receipt.id)


@dataclass(slots=True)
class RunHistorySelection:
    candidate_count: int = 0
    admitted_receipt_ids: list[UUID] = field(default_factory=list[UUID])
    completed_receipt_ids: set[UUID] = field(default_factory=set[UUID])
    purged_run_ids: list[UUID] = field(default_factory=list[UUID])


class FlowRunHistoryDeletion:
    def __init__(
        self, session: AsyncSession, *, family_rows: int | None = None
    ) -> None:
        self.session = session
        self.receipts = RetentionReceiptService(RetentionReceiptRepository(session))
        self.runs = FlowRunDeletionRepository(session)
        self.rules = FlowRunHistoryDueRepository(session)
        self.families = FlowFileFamilyRepository(session)
        self.housekeeping = FlowHousekeepingRepository(session)
        # The largest family settled in one transaction (RETENTION_MAX_FAMILY_ROWS).
        self.family_rows = (
            family_rows
            if family_rows is not None
            else get_settings().retention_max_family_rows
        )

    async def lock(self) -> None:
        """Acquire the Flow history guard before selecting deletion candidates."""
        await acquire_shared(self.session, RetentionSubject.FLOW_HISTORY)

    async def candidates(
        self,
        rule: FlowHistoryRule,
        *,
        now: datetime,
        after: tuple[datetime, UUID] | None,
        limit: int,
        trigger: RetentionTrigger,
    ) -> list[DueRun]:
        return await self.runs.due_runs(
            flow_id=rule.flow_id,
            cutoff=rule.cutoff(now),
            after=after,
            limit=limit,
            trigger=trigger,
        )

    def due_candidates(
        self,
        *,
        now: datetime,
        modes: tuple[FlowRunRetentionMode, ...],
        trigger: RetentionTrigger,
        triggered_by_user_id: UUID | None,
        out: RetentionEffects,
        selection: RunHistorySelection,
        scope: PurgeScope | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> Callable[[RetentionKeyset | None], Awaitable[RetentionUnitCandidate | None]]:
        """One due candidate at a time; pending receipts live only in this gather."""
        pending: tuple[RetentionKeyset, RetentionReceipt] | None = None

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            nonlocal pending
            if pending is not None:
                key, receipt = pending

                async def continue_run(rows: int, files: int) -> RetentionUnitUsage:
                    nonlocal pending
                    out.add(None, FlowsHistoryCount.RECEIPTS_EXAMINED.value)
                    progress = await self.advance(
                        receipt, rows=rows, files=files, out=out
                    )
                    current = progress.receipt
                    if (
                        current is not None
                        and current.state.phase is ReceiptPhase.COMPLETED
                    ):
                        selection.completed_receipt_ids.add(current.id)
                        selection.purged_run_ids.append(current.entity_id)
                    pending = (
                        (key, current)
                        if current is not None
                        and progress.usage.disposition
                        is RetentionUnitDisposition.CONTINUE
                        else None
                    )
                    # The due index excludes fenced runs; this transaction may
                    # re-offer positive units, then durable receipts resume later.
                    return (
                        replace(
                            progress.usage, disposition=RetentionUnitDisposition.DONE
                        )
                        if progress.usage.disposition
                        is RetentionUnitDisposition.CONTINUE
                        else progress.usage
                    )

                return key, continue_run
            if limit is not None and selection.candidate_count >= limit:
                return None
            rules = await self.rules.rules(
                now=now,
                modes=modes,
                after=after.group if after is not None else None,
                inclusive=after is None or after.at != FLOW_HISTORY_END,
                limit=1,
                tenant_id=scope.tenant_id if scope is not None else None,
                space_id=scope.space_id if scope is not None else None,
                flow_id=scope.flow_id if scope is not None else None,
                trigger=trigger,
            )
            if not rules:
                return None
            rule = rules[0]
            candidates = (
                []
                if rule.held
                else await self.candidates(
                    rule,
                    now=now,
                    after=(after.at, after.id)
                    if after is not None and after.group == rule.flow_id
                    else None,
                    limit=1,
                    trigger=trigger,
                )
            )
            due = candidates[0] if candidates else None
            key = RetentionKeyset(
                at=due.anchor if due is not None else FLOW_HISTORY_END,
                id=due.run_id if due is not None else FLOW_HISTORY_LAST_ID,
                group=rule.flow_id,
            )

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                nonlocal pending
                out.add(None, FlowsHistoryCount.FLOWS_EXAMINED.value)
                if rule.held:
                    out.blocked[RunBlock.HELD.value] += 1
                    return RetentionUnitUsage(1, 0)
                if due is None:
                    return RetentionUnitUsage(1, 0)
                out.add(None, FlowsHistoryCount.RUNS_EXAMINED.value)
                reason = due_blocked_reason(due)
                if reason is not None:
                    out.blocked[reason.value] += 1
                    return RetentionUnitUsage(2, 0)
                if dry_run:
                    selection.candidate_count += 1
                    return RetentionUnitUsage(2, 0)
                progress = await self.admit(
                    rule,
                    due,
                    trigger=trigger,
                    triggered_by_user_id=triggered_by_user_id,
                    out=out,
                    rows=rows,
                    now=now,
                )
                if progress.receipt is not None:
                    selection.candidate_count += 1
                    selection.admitted_receipt_ids.append(progress.receipt.id)
                    pending = key, progress.receipt
                return (
                    replace(progress.usage, disposition=RetentionUnitDisposition.DONE)
                    if progress.usage.disposition is RetentionUnitDisposition.CONTINUE
                    else progress.usage
                )

            return key, handle

        return next_candidate

    async def admit(
        self,
        rule: FlowHistoryRule,
        due: DueRun,
        *,
        trigger: RetentionTrigger,
        triggered_by_user_id: UUID | None,
        out: RetentionEffects,
        rows: int,
        now: datetime,
    ) -> RunDeletionProgress:
        """Lock a selected candidate, recheck it on the locked row and open its
        receipt; typed progress records work even when admission is refused."""
        if rows < RUN_ADMISSION_ROWS:
            return RunDeletionProgress(
                RetentionUnitUsage(2, 0, RetentionUnitDisposition.DOES_NOT_FIT), None
            )
        used = 3  # the rule, due run and locked-row lookup
        run = await self.runs.lock_run(due.run_id)
        if run is None:
            out.blocked[RunBlock.LOCK_DEFERRED] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), None)
        if run.retention_receipt_id is not None:
            out.blocked[RunBlock.ALREADY_ADMITTED.value] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), None)
        if run.anchor > rule.cutoff(now):
            out.blocked[RunBlock.NOT_DUE.value] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), None)
        used += 1
        blockers = await self.runs.admissible(run.id)
        if not blockers.clear:
            out.blocked[_blocked_reason(blockers)] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), None)
        used += 1
        if await self.runs.root_without_content(run.id):
            out.blocked[RunBlock.FILE_WITHOUT_CONTENT] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), None)
        receipt = await self.receipts.open(
            NewRetentionReceipt(
                task=FLOWS_HISTORY_TASK,
                entity_kind=RetentionEntityKind.FLOW_RUN,
                entity_id=run.id,
                category=RetentionCategory.RUN_RECORD,
                tenant_id=run.tenant_id,
                flow_id=run.flow_id,
                space_id=rule.space_id,
                policy_source=rule.source,
                policy_scope_id=rule.scope_id,
                policy_mode=rule.mode.value,
                policy_days=rule.days,
                anchor_at=run.anchor,
                due_at=run.anchor + timedelta(days=rule.days),
                trigger=trigger,
                triggered_by_user_id=triggered_by_user_id,
            )
        )
        # The run was checked on its locked row above, in this transaction.
        await self.runs.fence(run.id, receipt.id)
        _record(out, receipt, FlowsHistoryCount.RUNS_ADMITTED)
        return RunDeletionProgress(
            RetentionUnitUsage(used + 1, 0, RetentionUnitDisposition.CONTINUE), receipt
        )

    async def advance(
        self,
        receipt: RetentionReceipt,
        *,
        rows: int,
        files: int,
        out: RetentionEffects,
    ) -> RunDeletionProgress:
        """One fresh family or bounded child-row unit; no proof crosses a call."""
        used = 1  # the selected or re-offered receipt

        def stopped(
            disposition: RetentionUnitDisposition = RetentionUnitDisposition.DONE,
        ) -> RunDeletionProgress:
            return RunDeletionProgress(
                RetentionUnitUsage(used, 0, disposition), receipt
            )

        if receipt.state.is_final:
            return stopped()
        if rows < used + 3:
            return stopped(RetentionUnitDisposition.DOES_NOT_FIT)
        if receipt.flow_id is None:
            raise InvalidReceiptTransition("A Flow run deletion names its Flow.")
        used += 1
        if await self.runs.held(run_id=receipt.entity_id, flow_id=receipt.flow_id):
            if receipt.state.phase is not ReceiptPhase.PAUSED:
                receipt = await self.receipts.pause(receipt, ReceiptReason.LEGAL_HOLD)
            out.blocked[ReceiptReason.LEGAL_HOLD.value] += 1
            return stopped()
        used += 1
        run = await self.runs.lock_run(receipt.entity_id)
        used += 1
        if run is None:
            if await self.runs.run_exists(receipt.entity_id):
                out.blocked[RunBlock.LOCK_DEFERRED.value] += 1
                return stopped()
        else:
            blockers = await self.runs.admissible(run.id)
            if blockers.undelivered_audit or blockers.unresolved_webhook:
                reason = _delivery_reason(blockers)
                if receipt.state.phase is not ReceiptPhase.PAUSED:
                    receipt = await self.receipts.pause(receipt, reason)
                out.blocked[reason.value] += 1
                return stopped()
        if receipt.state.phase is ReceiptPhase.PAUSED:
            receipt = await self.receipts.resume(receipt)
            _record(out, receipt, FlowsHistoryCount.RECEIPTS_RESUMED)
        if receipt.state.phase is ReceiptPhase.PENDING:
            # Reserve root and binding reads before selecting the next family.
            if run is not None:
                if rows < used + 3:
                    return stopped(RetentionUnitDisposition.DOES_NOT_FIT)
                used += 1
                root = await self.families.next_run_family(run.id)
                if isinstance(root, FamilyBlock):
                    reason = ReceiptReason.FAMILY_DEPTH_EXCEEDED
                    receipt = await self.receipts.pause(receipt, reason)
                    out.blocked[reason.value] += 1
                    return stopped()
                if root is not None:
                    return await self._settle_family(
                        receipt,
                        run_id=run.id,
                        root=root,
                        rows=rows,
                        files=files,
                        initial_rows=used,
                        out=out,
                    )
            receipt = await self.receipts.append_manifest(
                receipt, [], manifest_after=None, complete=True
            )
            receipt = await self.receipts.release(receipt)
        if run is not None:
            if rows <= used:
                return stopped(RetentionUnitDisposition.DOES_NOT_FIT)
            deletion = await self.runs.delete_children(
                receipt.entity_id, limit=rows - used
            )
            used += deletion.rows
            if not deletion.root_deleted:
                _record(
                    out, receipt, FlowsHistoryCount.CHILD_ROWS_DELETED, deletion.rows
                )
                receipt = await self.receipts.record(
                    receipt, rows_deleted=deletion.rows
                )
                return stopped(RetentionUnitDisposition.CONTINUE)
            _record(
                out, receipt, FlowsHistoryCount.CHILD_ROWS_DELETED, deletion.rows - 1
            )
            _record(out, receipt, FlowsHistoryCount.RUNS_DELETED)
            receipt = await self.receipts.advance(
                receipt, ReceiptPhase.DELETING, rows_deleted=deletion.rows
            )
        else:
            receipt = await self.receipts.advance(receipt, ReceiptPhase.DELETING)
        receipt = await self.receipts.advance(receipt, ReceiptPhase.COMPLETED)
        _record(out, receipt, FlowsHistoryCount.RECEIPTS_COMPLETED)
        return stopped()

    async def _settle_family(
        self,
        receipt: RetentionReceipt,
        *,
        run_id: UUID,
        root: UUID,
        rows: int,
        files: int,
        initial_rows: int,
        out: RetentionEffects,
    ) -> RunDeletionProgress:
        locked, examined = await self.runs.lock_binding(root)
        used = initial_rows + examined
        if not locked:
            out.blocked[RunBlock.LOCK_DEFERRED.value] += 1
            return RunDeletionProgress(RetentionUnitUsage(used, 0), receipt)
        prepared = await prepare_file_family(
            self.families,
            root,
            rows=rows,
            files=files,
            cap=self.family_rows,
            initial_rows=used,
        )
        if isinstance(prepared, FileFamilyPreparationStopped):
            if prepared.pause_reason is not None:
                out.blocked[prepared.pause_reason.value] += 1
                receipt = await self.receipts.pause(receipt, prepared.pause_reason)
            elif prepared.usage.disposition is RetentionUnitDisposition.DONE:
                out.blocked[RunBlock.LOCK_DEFERRED.value] += 1
            return RunDeletionProgress(prepared.usage, receipt)

        # Own-link count/deletion and the conditional shared-upload predicate
        # must fit the complete atomic unit before the first manifest write.
        cap_links = (self.family_rows - prepared.total_rows - 1) // 2
        fit_links = (rows - prepared.total_rows - 1) // 2
        used = prepared.examined_rows
        if cap_links < 0:
            reason = ReceiptReason.FAMILY_EXCEEDS_BUDGET
            out.blocked[reason.value] += 1
            receipt = await self.receipts.pause(receipt, reason)
            return RunDeletionProgress(RetentionUnitUsage(used, 0), receipt)
        if fit_links < 0:
            return RunDeletionProgress(
                RetentionUnitUsage(used, 0, RetentionUnitDisposition.DOES_NOT_FIT),
                receipt,
            )
        links = await self.families.count_run_links(
            root, run_id=run_id, limit=min(cap_links, fit_links) + 1
        )
        used += links
        if links > cap_links:
            reason = ReceiptReason.FAMILY_EXCEEDS_BUDGET
            out.blocked[reason.value] += 1
            receipt = await self.receipts.pause(receipt, reason)
            return RunDeletionProgress(RetentionUnitUsage(used, 0), receipt)
        if links > fit_links:
            return RunDeletionProgress(
                RetentionUnitUsage(used, 0, RetentionUnitDisposition.DOES_NOT_FIT),
                receipt,
            )
        receipt = await self.receipts.append_manifest(
            receipt, prepared.manifest, manifest_after=None, complete=False
        )
        _record(out, receipt, FlowsHistoryCount.MANIFEST_ITEMS, len(prepared.manifest))
        deleted_links = await self.runs.drop_links(
            run_id, [member.file_id for member in prepared.members]
        )
        if deleted_links != links:
            raise FamilyChangedUnderLock(
                "The run's locked file links changed after bounded preparation."
            )
        used += deleted_links
        _record(out, receipt, FlowsHistoryCount.CHILD_ROWS_DELETED, deleted_links)
        used += len(prepared.members)
        block = await self.families.outside_owner(
            root, prepared.members, root_anchor_edges=UPLOAD_ANCHOR_EDGES
        )
        deleted = 0
        if block is not None:
            used += 1
            consumed = await self.runs.upload_consumed(root)
            bindings = transcripts = 0
            if not consumed:
                bindings = await self.housekeeping.release_upload_binding(root)
                transcripts = await self.housekeeping.release_bound_transcripts(root)
            out.blocked[RunBlock.SHARED.value] += 1
            file_usage = len(prepared.manifest) + bindings + transcripts
        else:
            bindings = await self.housekeeping.release_upload_binding(root)
            transcripts = await self.housekeeping.release_bound_transcripts(root)
            deleted = await self.families.delete_members(prepared.members)
            _record(out, receipt, FlowsHistoryCount.FILES_DELETED, deleted)
            _record(
                out,
                receipt,
                FlowsHistoryCount.REFERENCES_RELEASED,
                len(prepared.manifest),
            )
            file_usage = 2 * len(prepared.manifest) + deleted + bindings + transcripts
        _record(out, receipt, FlowsHistoryCount.BINDINGS_RELEASED, bindings)
        _record(out, receipt, FlowsHistoryCount.TRANSCRIPTS_DELETED, transcripts)
        receipt = await self.receipts.record(
            receipt, files_deleted=deleted, rows_deleted=deleted_links
        )
        return RunDeletionProgress(
            RetentionUnitUsage(used, file_usage, RetentionUnitDisposition.CONTINUE),
            receipt,
        )


@dataclass(frozen=True, slots=True)
class PurgeScope:
    tenant_id: UUID
    space_id: UUID | None = None
    flow_id: UUID | None = None
