"""Flows adopter for bounded staging, file-family and waste-data retention.

Audio-after-use releases eligible terminal-run input families while preserving
run and transcript history. Abandoned uploads use their own eligibility rule.
Unfinished family receipts repeat the complete ownership proof each time.

The shared runner owns transactions, progress, required audit and execution
budgets. Each family reuses bounded preparation and deepest-first guarded file
deletion. A unit that does not fit retains its cursor before the candidate;
busy, held and ineligible units advance to be revisited on the next pass.
Every step first takes the shared history
lock so policy/hold changes cannot overlap its FRESH checks and deletion.
"""

from __future__ import annotations

import logging
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
    RetentionContractError,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_step_order import rotate_retention_steps
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
from eneo.database.tables.files_table import Files
from eneo.flows.application.flow_file_family_preparation import (
    FileFamilyPreparationStopped,
    prepare_file_family,
)
from eneo.flows.application.step_assistant_reclamation import (
    STEP_ASSISTANT_BLOCKED_KEYS,
    STEP_ASSISTANT_COUNT_KEYS,
    STEP_ASSISTANTS_STEP,
    StepAssistantReclamation,
)
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.enums import FlowRuntimeInputFormat
from eneo.flows.infrastructure.flow_audio_after_use_repo import (
    AudioSourceAvailability,
    AudioSourceRun,
    FlowAudioAfterUseRepository,
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
from eneo.flows.infrastructure.flow_run_released_input_repo import (
    FlowRunReleasedInputRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_runtime import load_published_definition
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import BadRequestException, NotFoundException

logger = logging.getLogger(__name__)

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
        "audio_candidates_examined",
        "audio_source_checks",
        "audio_definition_checks",
        "audio_transcript_checks",
        "audio_bindings_checked",
        "audio_uploads_checked",
        "audio_inputs_released",
        "released_inputs_recorded",
        *PHYSICAL_CONFIRMATION_COUNT_KEYS,
        *RECEIPT_PRUNING_COUNT_KEYS,
        *STEP_ASSISTANT_COUNT_KEYS,
    }
)
_BLOCKED_KEYS = frozenset(
    {
        "held",
        "lock_deferred",
        "recorded",
        "audit_log_retained",
        "source_retention_active",
        "audio_not_eligible",
        "audio_definition_invalid",
        "canonical_transcript_missing",
        *PHYSICAL_CONFIRMATION_BLOCKED_KEYS,
        *(reason.value for reason in ReceiptReason),
        *STEP_ASSISTANT_BLOCKED_KEYS,
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
        settings: Settings | None = None,
    ) -> None:
        settings = settings if settings is not None else get_settings()
        self._now = now
        self._session = session
        self._family_rows = (
            family_rows
            if family_rows is not None
            else settings.retention_max_family_rows
        )
        self._chunk_rows = (
            chunk_rows if chunk_rows is not None else settings.retention_chunk_rows
        )
        self._gather_seconds = settings.retention_family_gather_seconds
        self._receipts = RetentionReceiptService(RetentionReceiptRepository(session))
        self._job_runs = RetentionJobRunRepository(session)
        self._families = FlowFileFamilyRepository(session)
        self._housekeeping = FlowHousekeepingRepository(session)
        self._audio = FlowAudioAfterUseRepository(session)
        self._versions = FlowVersionRepository(session)
        self._released_inputs = FlowRunReleasedInputRepository(session)
        self._transcripts = LiveTranscriptRepository(session)
        self._step_assistants = StepAssistantReclamation(
            session,
            family_rows=self._family_rows,
            chunk_rows=self._chunk_rows,
            settings=settings,
        )

    @property
    def name(self) -> str:
        return FLOWS_HOUSEKEEPING_TASK

    def steps(self) -> Sequence[RetentionStep]:
        family = self._family_rows
        families = (
            ("file_families", self._file_families, family),
            ("abandoned_uploads", self._abandoned_uploads, family),
            ("audio_after_use", self._audio_after_use, family),
        )
        first = rotate_retention_steps(
            tuple(
                RetentionStep(name, self._after_flow_history_lock(run), max_batch=batch)
                for name, run, batch in families
            ),
            execution_date=self._now().astimezone(timezone.utc).date(),
        )
        return (
            *first,
            *(
                RetentionStep(
                    name,
                    self._after_flow_history_lock(run),
                    max_batch=batch,
                    max_files=0 if name == STEP_ASSISTANTS_STEP else None,
                )
                for name, run, batch in (
                    ("live_transcripts", self._live_transcripts, None),
                    ("audit_outbox", self._audit_outbox, None),
                    (STEP_ASSISTANTS_STEP, self._step_assistants.step, family),
                    ("physical_confirmation", self._receipts.physical_step, None),
                    ("prune_receipts", self._prune_receipts, None),
                    ("prune_job_runs", self._prune_job_runs, None),
                )
            ),
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
                if receipt.category is RetentionCategory.AUDIO_AFTER_USE:
                    if receipt.source_run_id is None:
                        raise RetentionContractError(
                            "An audio proof must identify its source run."
                        )
                    return await self._reclaim_audio(
                        receipt.entity_id,
                        run_id=receipt.source_run_id,
                        rows=rows,
                        files=files,
                        out=out,
                        receipt=receipt,
                    )
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
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=self._chunk_rows,
            gather_seconds=self._gather_seconds,
            clock=time.monotonic,
            min_candidate_rows=3,
        )

    async def _audio_after_use(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            binding = await self._audio.next_binding(after)
            if binding is None:
                return None

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                if await self._housekeeping.recorded_families(
                    task=FLOWS_HOUSEKEEPING_TASK,
                    category=RetentionCategory.AUDIO_AFTER_USE,
                    root_ids=[binding.file_id],
                ):
                    out.blocked["recorded"] += 1
                    return RetentionUnitUsage(rows=1, files=0)
                return await self._reclaim_audio(
                    binding.file_id,
                    run_id=binding.run_id,
                    candidate_step_id=binding.step_id,
                    rows=rows,
                    files=files,
                    out=out,
                )

            return binding.position, handle

        return await gather_retention_units(
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=self._chunk_rows,
            gather_seconds=self._gather_seconds,
            min_candidate_rows=3,
        )

    async def _audio_receipt(
        self,
        root: UUID,
        source: AudioSourceRun,
        receipt: RetentionReceipt | None,
    ) -> RetentionReceipt:
        if receipt is None:
            receipt = await self._receipts.open(
                NewRetentionReceipt(
                    task=FLOWS_HOUSEKEEPING_TASK,
                    entity_kind=RetentionEntityKind.FILE_FAMILY,
                    entity_id=root,
                    category=RetentionCategory.AUDIO_AFTER_USE,
                    tenant_id=source.tenant_id,
                    flow_id=source.flow_id,
                    source_run_id=source.id,
                    anchor_at=source.anchor_at,
                    policy_source=source.policy_source,
                    policy_scope_id=source.policy_scope_id,
                )
            )
        if receipt.state.phase is ReceiptPhase.PAUSED:
            receipt = await self._receipts.resume(receipt)
        return receipt

    async def _withdraw_audio(
        self, receipt: RetentionReceipt | None, out: RetentionEffects
    ) -> None:
        if receipt is not None:
            if receipt.state.phase is ReceiptPhase.PAUSED:
                receipt = await self._receipts.resume(receipt)
            await self._receipts.withdraw(receipt)
            out.add(receipt.tenant_id, "receipts_withdrawn")

    async def _reclaim_audio(
        self,
        root: UUID,
        *,
        run_id: UUID,
        rows: int,
        files: int,
        out: RetentionEffects,
        receipt: RetentionReceipt | None = None,
        candidate_step_id: UUID | None = None,
    ) -> RetentionUnitUsage:
        out.add(None, "audio_candidates_examined")
        source = await self._audio.lock_source(run_id)
        out.add(None, "audio_source_checks")
        if source is None:
            availability = await self._audio.source_availability(run_id)
            out.add(None, "audio_source_checks")
            match availability:
                case AudioSourceAvailability.BUSY:
                    out.blocked["lock_deferred"] += 1
                case AudioSourceAvailability.RETENTION_ACTIVE:
                    out.blocked["source_retention_active"] += 1
                case (
                    AudioSourceAvailability.MISSING | AudioSourceAvailability.INELIGIBLE
                ):
                    await self._withdraw_audio(receipt, out)
                    out.blocked["audio_not_eligible"] += 1
            return RetentionUnitUsage(rows=3, files=0)
        if source.held:
            out.blocked["held"] += 1
            return RetentionUnitUsage(rows=2, files=0)
        out.add(source.tenant_id, "audio_definition_checks")
        try:
            definition = await load_published_definition(
                flow_version_repo=self._versions,
                flow_id=source.flow_id,
                version=source.version,
                tenant_id=source.tenant_id,
            )
        except (BadRequestException, FlowRuntimeInvariantError, NotFoundException):
            logger.warning(
                "Audio retention cannot inspect source run %s", run_id, exc_info=True
            )
            out.blocked["audio_definition_invalid"] += 1
            return RetentionUnitUsage(rows=3, files=0)
        audio_steps = {
            step.step_id
            for step in definition.runtime_steps()
            if (config := build_runtime_input_config(step.input_config)).enabled
            and config.input_format is FlowRuntimeInputFormat.AUDIO
        }
        if candidate_step_id is not None and candidate_step_id not in audio_steps:
            out.blocked["audio_not_eligible"] += 1
            return RetentionUnitUsage(rows=3, files=0)
        prepared = await prepare_file_family(
            self._families,
            root,
            rows=rows,
            files=files,
            cap=self._family_rows,
            initial_rows=3,
        )
        if isinstance(prepared, FileFamilyPreparationStopped):
            if prepared.pause_reason is not None:
                receipt = await self._audio_receipt(root, source, receipt)
                await self._pause(receipt, prepared.pause_reason, out)
            elif prepared.usage.disposition is RetentionUnitDisposition.DONE:
                out.blocked["lock_deferred"] += 1
            return prepared.usage
        used = prepared.examined_rows

        async def no_room() -> RetentionUnitUsage:
            if rows >= self._family_rows:
                pending = await self._audio_receipt(root, source, receipt)
                await self._pause(pending, ReceiptReason.FAMILY_EXCEEDS_BUDGET, out)
                return RetentionUnitUsage(rows=used, files=0)
            return RetentionUnitUsage(
                rows=used, files=0, disposition=RetentionUnitDisposition.DOES_NOT_FIT
            )

        maximum = min(rows, self._family_rows)
        links = await self._families.input_links(
            prepared.members,
            run_id=run_id,
            limit=(maximum - prepared.total_rows) // 3,
        )
        used += links.examined
        out.add(source.tenant_id, "audio_bindings_checked", links.examined)
        if links.items is None:
            return await no_room()
        transcription_steps = {step_id for step_id, _ in links.items} & audio_steps
        if not transcription_steps:
            await self._withdraw_audio(receipt, out)
            out.blocked["audio_not_eligible"] += 1
            return RetentionUnitUsage(rows=used, files=0)
        # Each input is examined, detached and recorded; each transcript check
        # may read its result and canonical source. Reserve before reading it.
        needed_rows = (
            prepared.total_rows + 3 * len(links.items) + 2 * len(transcription_steps)
        )
        if needed_rows > maximum:
            return await no_room()
        for step_id in sorted(transcription_steps):
            available = await self._audio.transcript_safe_to_release(run_id, step_id)
            used += 2
            out.add(source.tenant_id, "audio_transcript_checks", 2)
            if not available:
                out.blocked["canonical_transcript_missing"] += 1
                return RetentionUnitUsage(rows=used, files=0)
        member_ids = [member.file_id for member in prepared.members]
        uploads = await self._audio.removable_uploads(
            source,
            member_ids,
            limit=(maximum - needed_rows) // 2,
        )
        used += len(uploads)
        out.add(source.tenant_id, "audio_uploads_checked", len(uploads))
        if needed_rows + 2 * len(uploads) > maximum:
            return await no_room()
        if prepared.total_files + 2 * len(links.items) + len(uploads) > files:
            return RetentionUnitUsage(
                rows=used, files=0, disposition=RetentionUnitDisposition.DOES_NOT_FIT
            )
        receipt = await self._audio_receipt(root, source, receipt)
        recorded = deleted = 0
        async with self._session.begin_nested() as detached:
            inputs_deleted, uploads_deleted = await self._audio.detach(
                run_id=run_id,
                members=member_ids,
                uploads=uploads,
            )
            used += inputs_deleted + uploads_deleted
            used += len(prepared.members)
            block = await self._families.outside_owner(
                root,
                prepared.members,
                root_anchor_edges=frozenset({Files.__tablename__}),
            )
            if block is not None:
                await detached.rollback()
            else:
                receipt = await self._receipts.append_manifest(
                    receipt,
                    prepared.manifest,
                    manifest_after=None,
                    complete=True,
                )
                recorded = await self._released_inputs.record(
                    run_id=run_id,
                    bindings=links.items,
                    at=self._now(),
                )
                receipt = await self._receipts.release(receipt)
                receipt = await self._receipts.advance(receipt, ReceiptPhase.DELETING)
                deleted = await self._families.delete_members(prepared.members)
                receipt = await self._receipts.advance(
                    receipt, ReceiptPhase.COMPLETED, files_deleted=deleted
                )
        out.add(source.tenant_id, "members_checked", len(prepared.members))
        if block is not None:
            await self._pause(receipt, _block_reason(block), out)
            return RetentionUnitUsage(rows=used, files=inputs_deleted + uploads_deleted)
        for key, value in (
            ("manifest_items", len(prepared.manifest)),
            ("audio_inputs_released", inputs_deleted),
            ("anchors_released", uploads_deleted),
            ("released_inputs_recorded", recorded),
            ("references_released", len(prepared.manifest)),
            ("files_deleted", deleted),
            ("families_completed", 1),
        ):
            out.add(source.tenant_id, key, value)
        out.receipts[source.tenant_id].append(receipt.id)
        return RetentionUnitUsage(
            rows=used + recorded,
            files=2 * len(prepared.manifest)
            + deleted
            + inputs_deleted
            + uploads_deleted
            + recorded,
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
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
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
        prepared = await prepare_file_family(
            self._families,
            root,
            rows=rows,
            files=files,
            cap=self._family_rows,
            initial_rows=1,
        )
        if isinstance(prepared, FileFamilyPreparationStopped):
            if prepared.pause_reason is not None:
                receipt = await self._receipt(root, receipt, upload)
                await self._pause(receipt, prepared.pause_reason, out)
            elif prepared.usage.disposition is RetentionUnitDisposition.DONE:
                out.blocked["lock_deferred"] += 1
            return prepared.usage
        members_locked, pairs = prepared.members, prepared.manifest
        used = prepared.examined_rows
        receipt = await self._receipt(root, receipt, upload)
        tenant_id = receipt.tenant_id
        out.add(tenant_id, "members_checked", len(members_locked))
        used += len(members_locked)
        block = await self._families.outside_owner(
            root, members_locked, root_anchor_edges=UPLOAD_ANCHOR_EDGES
        )
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
