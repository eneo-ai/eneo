"""Gallring runner and the flows.housekeeping task against real PostgreSQL.

Every test commits its fixtures, because the runner commits chunk by chunk in its
own sessions, and observes the effect through fresh sessions.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.application.gallring_runner import (
    GallringChunkLimits,
    GallringRunner,
    GallringRunReport,
)
from eneo.data_retention.domain.gallring import (
    GallringBudget,
    GallringCategory,
    GallringJobOutcome,
    ReceiptItemDisposition,
    ReceiptPhase,
    ReceiptReason,
    gallring_batch_audit_id,
)
from eneo.data_retention.infrastructure.gallring_job_run_repo import (
    GallringJobRunRepository,
)
from eneo.data_retention.infrastructure.gallring_lock import (
    GallringLockBusy,
    GallringSubject,
    acquire_exclusive,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowTemplateAssets,
    FlowVersions,
)
from eneo.database.tables.gallring_tables import (
    GallringJobRuns,
    GallringReceiptItems,
    GallringReceipts,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_models import FileContentVariant, FileType
from eneo.flows.application.flow_housekeeping_task import (
    FLOWS_HOUSEKEEPING_TASK,
    FlowHousekeepingTask,
)
from eneo.flows.enums import FlowRunStatus
from eneo.flows.infrastructure.flow_file_family_repo import FlowFileFamilyRepository
from eneo.flows.infrastructure.flow_housekeeping_repo import FlowHousekeepingRepository
from eneo.flows.infrastructure.flow_retention_hold_repo import (
    FlowRetentionHoldRepository,
)
from eneo.flows.runtime.flow_runtime_health import (
    build_flow_runtime_health_policy,
    load_flow_runtime_health_snapshot,
)
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.object_content.content import ContentAccessClass, ContentState, StorageKind

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_NOW = datetime.now(timezone.utc)


@asynccontextmanager
async def _committed() -> AsyncIterator[AsyncSession]:
    async with sessionmanager.session() as session, session.begin():
        yield session


async def _space(tenant_id: UUID, user_id: UUID) -> UUID:
    async with _committed() as session:
        space = Spaces(
            name=f"Gallring space {uuid4()}",
            description=None,
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_space_id=None,
            data_retention_days=None,
        )
        session.add(space)
        await session.flush()
        return space.id


async def _flow(tenant_id: UUID, user_id: UUID, space_id: UUID) -> UUID:
    async with _committed() as session:
        flow = Flows(
            name=f"Gallring flow {uuid4()}",
            description=None,
            tenant_id=tenant_id,
            space_id=space_id,
            created_by_user_id=user_id,
            owner_user_id=user_id,
            published_version=None,
            metadata_json={},
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
        session.add(flow)
        await session.flush()
        return flow.id


async def _file(
    tenant_id: UUID, user_id: UUID, *, parent_file_id: UUID | None = None
) -> tuple[UUID, UUID]:
    """A file with one durable content; returns (file id, content id)."""
    payload = uuid4().bytes * 8
    async with _committed() as session:
        file = Files(
            name=f"personal-{uuid4()}.txt",
            mimetype="text/plain",
            file_type=FileType.TEXT.value,
            owner_type="user",
            owner_user_id=user_id,
            owner_service_id=None,
            tenant_id=tenant_id,
            parent_file_id=parent_file_id,
        )
        session.add(file)
        key = f"gallring-test-{uuid4()}"
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            storage_kind=StorageKind.POSTGRES_INLINE.value,
            state=ContentState.AVAILABLE.value,
            access_class=ContentAccessClass.PRIVATE_RESOURCE.value,
            sha256=sha256(payload).digest(),
            size_bytes=len(payload),
            declared_media_type="text/plain",
            verified_media_type="text/plain",
            idempotency_key=key,
            request_fingerprint=sha256(key.encode() + payload).digest(),
            available_at=_NOW,
        )
        session.add(content)
        await session.flush()
        session.add(
            InlineContentPayloads(
                content_id=content.id,
                storage_kind=StorageKind.POSTGRES_INLINE.value,
                payload=payload,
            )
        )
        session.add(
            FileContentReferences(
                file_id=file.id,
                content_id=content.id,
                variant=FileContentVariant.ORIGINAL.value,
                ordinal=0,
            )
        )
        return file.id, content.id


async def _more_references(
    tenant_id: UUID, user_id: UUID, file_id: UUID, count: int
) -> list[tuple[UUID, UUID]]:
    """Give the file `count` derived-page references, each with its own content."""
    pairs: list[tuple[UUID, UUID]] = []
    async with _committed() as session:
        for ordinal in range(count):
            payload = uuid4().bytes
            key = f"gallring-test-{uuid4()}"
            content = ObjectContents(
                tenant_id=tenant_id,
                created_by_user_id=user_id,
                storage_kind=StorageKind.POSTGRES_INLINE.value,
                state=ContentState.AVAILABLE.value,
                access_class=ContentAccessClass.PRIVATE_RESOURCE.value,
                sha256=sha256(payload).digest(),
                size_bytes=len(payload),
                declared_media_type="image/png",
                verified_media_type="image/png",
                idempotency_key=key,
                request_fingerprint=sha256(key.encode() + payload).digest(),
                available_at=_NOW,
            )
            session.add(content)
            await session.flush()
            session.add(
                InlineContentPayloads(
                    content_id=content.id,
                    storage_kind=StorageKind.POSTGRES_INLINE.value,
                    payload=payload,
                )
            )
            session.add(
                FileContentReferences(
                    file_id=file_id,
                    content_id=content.id,
                    variant=FileContentVariant.DERIVED_PAGE.value,
                    ordinal=ordinal,
                )
            )
            pairs.append((file_id, content.id))
    return pairs


async def _abandoned_upload(
    tenant_id: UUID, user_id: UUID, flow_id: UUID, *, children: int = 0
) -> list[tuple[UUID, UUID]]:
    """An upload 40 days old (past the 30-day default) with `children` derived files
    chained below it; returns the family's (file, content) pairs, root first."""
    family = [await _file(tenant_id, user_id)]
    for _ in range(children):
        family.append(await _file(tenant_id, user_id, parent_file_id=family[-1][0]))
    async with _committed() as session:
        uploaded_at = _NOW - timedelta(days=40)
        session.add(
            FlowRuntimeUploadedFiles(
                file_id=family[0][0],
                flow_id=flow_id,
                tenant_id=tenant_id,
                uploaded_for_step_id=uuid4(),
                owner_type="user",
                owner_user_id=user_id,
                owner_service_id=None,
                created_at=uploaded_at,
                updated_at=uploaded_at,
            )
        )
    return family


async def _age_upload(file_id: UUID, *, days: float) -> None:
    async with _committed() as session:
        await session.execute(
            sa.update(FlowRuntimeUploadedFiles)
            .where(FlowRuntimeUploadedFiles.file_id == file_id)
            .values(created_at=_NOW - timedelta(days=days))
        )


async def _transcript(
    tenant_id: UUID,
    user_id: UUID,
    flow_id: UUID,
    *,
    created_days_ago: int,
    bound_file_id: UUID | None = None,
) -> UUID:
    async with _committed() as session:
        created_at = _NOW - timedelta(days=created_days_ago)
        transcript = FlowLiveTranscripts(
            tenant_id=tenant_id,
            user_id=user_id,
            flow_id=flow_id,
            flow_version=1,
            step_id=uuid4(),
            model_id=uuid4(),
            recording_id=f"rec-{uuid4().hex[:8]}",
            text="Spoken words.",
            segments=None,
            received_audio_seconds=1.0,
            bound_file_id=bound_file_id,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(transcript)
        await session.flush()
        return transcript.id


async def _template_asset(
    tenant_id: UUID,
    user_id: UUID,
    flow_id: UUID,
    space_id: UUID,
    *,
    deleted_at: datetime | None,
    file_id: UUID | None = None,
) -> UUID:
    if file_id is None:
        file_id, _ = await _file(tenant_id, user_id)
    async with _committed() as session:
        asset = FlowTemplateAssets(
            flow_id=flow_id,
            space_id=space_id,
            tenant_id=tenant_id,
            file_id=file_id,
            name="template.docx",
            checksum=uuid4().hex,
            mimetype="application/octet-stream",
            placeholders=[],
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            status="ready",
            deleted_at=deleted_at,
        )
        session.add(asset)
        await session.flush()
        return asset.id


async def _delivered_outbox_row(tenant_id: UUID, user_id: UUID, flow_id: UUID) -> UUID:
    """A delivered outbox mirror whose audit log retention already deleted."""
    async with _committed() as session:
        if (
            await session.scalar(
                sa.select(FlowVersions.version).where(FlowVersions.flow_id == flow_id)
            )
            is None
        ):
            session.add(
                FlowVersions(
                    flow_id=flow_id,
                    version=1,
                    tenant_id=tenant_id,
                    definition_checksum=f"gallring-{uuid4()}",
                    definition_json={"schema_version": 1, "steps": []},
                )
            )
            await session.flush()
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=user_id,
            principal_service_id=None,
            tenant_id=tenant_id,
            trace_id=uuid4(),
            status=FlowRunStatus.COMPLETED.value,
            started_at=_NOW,
            finished_at=_NOW,
            input_payload_json={},
            output_payload_json={},
        )
        session.add(run)
        await session.flush()
        outbox = FlowRunAuditOutbox(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            run_revision=1,
            description="flow_run_completed:executor_completed",
            action="flow_run_completed",
            entity_type="flow_run",
            entity_id=run.id,
            actor_id=user_id,
            actor_type="user",
            source="executor_completed",
            target_status="completed",
            delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
            delivery_attempts=1,
            # Past the 365-day default audit retention.
            delivered_at=_NOW - timedelta(days=400),
        )
        session.add(outbox)
        await session.flush()
        return outbox.id


async def _place_hold(
    session: AsyncSession,
    tenant_id: UUID,
    flow_id: UUID,
    *,
    run_id: UUID | None = None,
) -> None:
    """A legal hold placed as the hold service does: EXCLUSIVE lock, then the row."""
    await acquire_exclusive(session, GallringSubject.FLOW_HISTORY)
    await FlowRetentionHoldRepository(session).insert(
        tenant_id=tenant_id,
        flow_id=flow_id,
        run_ids=[run_id],
        reason="Litigation",
        review_by=datetime.now(timezone.utc) + timedelta(days=30),
        ends_at=None,
        actor={"type": "system"},
        user_id=None,
    )


async def _until_a_session_waits_on_the_flow_history_lock() -> None:
    for _ in range(200):
        waiting = await _scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = "
                "'Lock' AND wait_event = 'advisory' AND datname = current_database()"
            )
        )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("no session waited on the flow history lock")


def _limits(chunk_rows: int, lock_timeout_ms: int = 2_000) -> GallringChunkLimits:
    return GallringChunkLimits(
        rows=chunk_rows,
        statement_timeout_ms=30_000,
        lock_timeout_ms=lock_timeout_ms,
        stale_after_seconds=3600,
    )


def _runner(
    session: AsyncSession,
    *,
    chunk_rows: int = 500,
    budget_rows: int = 100_000,
    budget_files: int = 100_000,
    budget_seconds: float = 600,
    clock: Callable[[], float] | None = None,
    lock_timeout_ms: int = 2_000,
) -> GallringRunner:
    return GallringRunner(
        session=session,
        job_runs=GallringJobRunRepository(session),
        audit_service=AuditService(repository=AuditLogRepositoryImpl(session)),
        budget=GallringBudget(
            rows=budget_rows, files=budget_files, seconds=budget_seconds
        ),
        limits=_limits(chunk_rows, lock_timeout_ms),
        **({"clock": clock} if clock is not None else {}),
    )


async def _housekeeping(
    *, family_rows: int | None = None, now: datetime | None = None, **limits: Any
) -> GallringRunReport:
    async with sessionmanager.session() as session:
        task = FlowHousekeepingTask(
            session,
            family_rows=family_rows,
            chunk_rows=limits.get("chunk_rows"),
            **({"now": lambda: now} if now is not None else {}),
        )
        return await _runner(session, **limits).run(task)


@asynccontextmanager
async def _rows_returned() -> AsyncIterator[list[tuple[str, int]]]:
    """Every statement the block sends, with the number of rows it returned."""
    seen: list[tuple[str, int]] = []
    engine = sessionmanager._engine  # noqa: SLF001
    assert engine is not None

    def keep(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, cursor.rowcount))

    event.listen(engine.sync_engine, "after_cursor_execute", keep)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", keep)


async def _scalar(statement: Any) -> Any:
    async with _committed() as session:
        return await session.scalar(statement)


async def _gallring_audits(tenant_id: UUID) -> list[AuditLogTable]:
    async with _committed() as session:
        audits = list(
            await session.scalars(
                sa.select(AuditLogTable)
                .where(
                    AuditLogTable.tenant_id == tenant_id,
                    AuditLogTable.action == ActionType.GALLRING_APPLIED.value,
                )
                .order_by(AuditLogTable.timestamp)
            )
        )
        session.expunge_all()
        return audits


async def _receipt(entity_id: UUID) -> GallringReceipts:
    async with _committed() as session:
        receipt = await session.scalar(
            sa.select(GallringReceipts).where(GallringReceipts.entity_id == entity_id)
        )
        assert receipt is not None
        session.expunge(receipt)
        return receipt


async def _existing_files(file_ids: list[UUID]) -> set[UUID]:
    async with _committed() as session:
        return set(
            await session.scalars(sa.select(Files.id).where(Files.id.in_(file_ids)))
        )


@pytest.fixture
async def scope(test_tenant, admin_user) -> tuple[UUID, UUID, UUID, UUID]:
    """(tenant id, user id, space id, flow id); the tenant leaves its window unset."""
    space_id = await _space(test_tenant.id, admin_user.id)
    flow_id = await _flow(test_tenant.id, admin_user.id, space_id)
    return test_tenant.id, admin_user.id, space_id, flow_id


# Descendant reclamation of abandoned uploads -----------------------------------


async def test_abandoned_upload_family_is_reclaimed_bottom_up_with_a_receipt(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=2)
    file_ids = [file_id for file_id, _ in family]

    report = await _housekeeping()

    assert report.outcome == GallringJobOutcome.SUCCEEDED
    assert await _existing_files(file_ids) == set()
    assert (
        await _scalar(
            sa.select(FlowRuntimeUploadedFiles.file_id).where(
                FlowRuntimeUploadedFiles.file_id == file_ids[0]
            )
        )
        is None
    )
    receipt = await _receipt(file_ids[0])
    assert receipt.phase == ReceiptPhase.COMPLETED.value
    assert receipt.manifest_completed_at is not None
    assert receipt.files_deleted == 3
    async with _committed() as session:
        items = set(
            (
                await session.execute(
                    sa.select(
                        GallringReceiptItems.file_id, GallringReceiptItems.content_id
                    ).where(GallringReceiptItems.receipt_id == receipt.id)
                )
            ).tuples()
        )
    assert items == set(family)
    [audit] = [
        audit
        for audit in await _gallring_audits(tenant_id)
        if audit.log_metadata["step"] == "abandoned_uploads"
    ]
    assert audit.log_metadata["receipt_ids"] == [str(receipt.id)]
    assert audit.log_metadata["counts"] == {
        "manifest_items": 3,
        "members_checked": 3,
        "anchors_released": 1,
        "files_deleted": 3,
        "references_released": 3,
        "families_completed": 1,
    }

    # The content owner deletes the bytes; the next run confirms them per item.
    async with _committed() as session:
        await session.execute(
            sa.delete(InlineContentPayloads).where(
                InlineContentPayloads.content_id.in_(
                    [content_id for _, content_id in family]
                )
            )
        )
        await session.execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id.in_([content_id for _, content_id in family]))
            .values(
                state=ContentState.TOMBSTONED.value, payload_deleted_at=sa.func.now()
            )
        )
    await _housekeeping()
    confirmed = await _receipt(file_ids[0])
    assert confirmed.physical_confirmed_at is not None
    async with _committed() as session:
        dispositions = set(
            await session.scalars(
                sa.select(GallringReceiptItems.disposition).where(
                    GallringReceiptItems.receipt_id == receipt.id
                )
            )
        )
    assert dispositions == {ReceiptItemDisposition.DELETED.value}


async def test_a_paused_family_completes_once_released_with_its_current_references(
    scope,
) -> None:
    tenant_id, user_id, space_id, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    file_ids = [file_id for file_id, _ in family]
    holder = await _template_asset(
        tenant_id, user_id, flow_id, space_id, deleted_at=None, file_id=file_ids[1]
    )
    paused = await _housekeeping()
    assert (await _receipt(file_ids[0])).reason == (
        ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE.value
    )
    assert paused.blocked["abandoned_uploads.derived_file_referenced_elsewhere"] == 1
    assert await _existing_files(file_ids) == set(file_ids)

    # While paused, the upload gets one more content reference, then the other
    # owner lets go of the derived file.
    [added] = await _more_references(tenant_id, user_id, file_ids[0], 1)
    async with _committed() as session:
        await session.execute(
            sa.delete(FlowTemplateAssets).where(FlowTemplateAssets.id == holder)
        )
    report = await _housekeeping()

    receipt = await _receipt(file_ids[0])
    assert receipt.phase == ReceiptPhase.COMPLETED.value
    assert report.counts["file_families.manifest_items"] == 3
    async with _committed() as session:
        items = set(
            (
                await session.execute(
                    sa.select(
                        GallringReceiptItems.file_id, GallringReceiptItems.content_id
                    ).where(GallringReceiptItems.receipt_id == receipt.id)
                )
            ).tuples()
        )
    assert items == {*family, added}
    assert await _existing_files(file_ids) == set()


async def test_an_owner_gained_while_paused_is_seen_by_a_fresh_check(
    scope,
) -> None:
    tenant_id, user_id, space_id, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    file_ids = [file_id for file_id, _ in family]
    child_holder = await _template_asset(
        tenant_id, user_id, flow_id, space_id, deleted_at=None, file_id=file_ids[1]
    )
    await _housekeeping()
    assert (await _receipt(file_ids[0])).reason == (
        ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE.value
    )

    # Before the next transaction the root gains an owner and the child loses
    # its own; the family is checked again from scratch, never from memory.
    await _template_asset(
        tenant_id, user_id, flow_id, space_id, deleted_at=None, file_id=file_ids[0]
    )
    async with _committed() as session:
        await session.execute(
            sa.delete(FlowTemplateAssets).where(FlowTemplateAssets.id == child_holder)
        )
    report = await _housekeeping()

    receipt = await _receipt(file_ids[0])
    assert (receipt.phase, receipt.reason) == (
        ReceiptPhase.PAUSED.value,
        ReceiptReason.FILE_REFERENCED_ELSEWHERE.value,
    )
    assert report.blocked["file_families.file_referenced_elsewhere"] == 1
    # Nothing of the family was released or deleted.
    assert await _existing_files(file_ids) == set(file_ids)
    assert (
        await _scalar(
            sa.select(FlowRuntimeUploadedFiles.file_id).where(
                FlowRuntimeUploadedFiles.file_id == file_ids[0]
            )
        )
        == file_ids[0]
    )
    assert (
        await _scalar(
            sa.select(sa.func.count()).where(
                GallringReceiptItems.receipt_id == receipt.id
            )
        )
        == 0
    )


async def test_a_deferred_family_gets_the_whole_budget_within_two_nights(
    scope,
) -> None:
    tenant_id, user_id, space_id, flow_id = scope
    # Three paused receipts of a held Flow cost a row each in file_families.
    held_flow_id = await _flow(tenant_id, user_id, space_id)
    async with _committed() as session:
        session.add_all(
            GallringReceipts(
                task=FLOWS_HOUSEKEEPING_TASK,
                entity_kind="file_family",
                entity_id=uuid4(),
                category="abandoned_upload",
                trigger="scheduled",
                tenant_id=tenant_id,
                flow_id=held_flow_id,
                phase="paused",
                paused_from_phase="pending",
                reason=ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE.value,
                started_at=_NOW,
                updated_at=_NOW,
            )
            for _ in range(3)
        )
        await _place_hold(session, tenant_id, held_flow_id)
    # Two files with a reference each: 14 examined rows, the whole nightly budget.
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    first_night = _NOW + timedelta(days=_NOW.date().toordinal() % 2)

    nights = [
        await _housekeeping(
            budget_rows=14, family_rows=14, now=first_night + timedelta(days=night)
        )
        for night in range(2)
    ]

    # file_families goes first on the first night and leaves too little; the
    # next night abandoned_uploads goes first with the whole budget.
    assert nights[0].blocked["abandoned_uploads.family_deferred"] == 1
    assert nights[1].counts["abandoned_uploads.families_completed"] == 1
    assert await _existing_files([f for f, _ in family]) == set()


async def test_a_family_at_or_over_the_cap_never_blocks_the_uploads_behind_it(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    # Cap 8: a family of five files is over it, the one-file family behind it
    # fits exactly (eight examined rows, the candidate included).
    big = await _abandoned_upload(tenant_id, user_id, flow_id, children=4)
    await _age_upload(big[0][0], days=50)
    small = await _abandoned_upload(tenant_id, user_id, flow_id)

    nights = [await _housekeeping(family_rows=8) for _ in range(3)]

    receipt = await _receipt(big[0][0])
    assert (receipt.phase, receipt.reason) == (
        ReceiptPhase.PAUSED.value,
        ReceiptReason.FAMILY_EXCEEDS_BUDGET.value,
    )
    assert (await _receipt(small[0][0])).phase == ReceiptPhase.COMPLETED.value
    assert nights[0].counts["abandoned_uploads.families_completed"] == 1
    # Looked at once more each night, within the cap, never in a loop.
    assert nights[1].blocked["file_families.family_exceeds_budget"] == 1
    assert all(night.outcome == GallringJobOutcome.SUCCEEDED for night in nights)
    assert await _existing_files([small[0][0]]) == set()
    assert await _existing_files([f for f, _ in big]) == {f for f, _ in big}


@pytest.mark.parametrize(
    ("transcripts", "cap", "phase"),
    [(0, 7, "paused"), (0, 8, "completed"), (1, 9, "paused")],
)
async def test_the_cap_counts_every_examined_row_of_a_family(
    scope, transcripts, cap, phase
) -> None:
    tenant_id, user_id, _, flow_id = scope
    # One file with a reference costs eight rows, the candidate included, and
    # two more for each bound transcript.
    family = await _abandoned_upload(tenant_id, user_id, flow_id)
    for _ in range(transcripts):
        await _transcript(
            tenant_id, user_id, flow_id, created_days_ago=40, bound_file_id=family[0][0]
        )

    report = await _housekeeping(family_rows=cap)

    assert (await _receipt(family[0][0])).phase == phase
    assert report.outcome == GallringJobOutcome.SUCCEEDED


@pytest.mark.parametrize(("budget", "remaining"), [(1, 2), (9, 1)])
async def test_one_row_left_defers_the_family_without_failing_the_execution(
    scope, budget, remaining
) -> None:
    # M81: a count sentinel with only the candidate row left overcharges the batch.
    tenant_id, user_id, _, flow_id = scope
    families = [await _abandoned_upload(tenant_id, user_id, flow_id) for _ in range(2)]
    files = [family[0][0] for family in families]

    report = await _housekeeping(family_rows=8, budget_rows=budget)

    assert report.outcome == GallringJobOutcome.PARTIAL
    assert report.error_code is None
    assert len(await _existing_files(files)) == remaining
    next_report = await _housekeeping(family_rows=8)
    assert next_report.outcome == GallringJobOutcome.SUCCEEDED
    assert await _existing_files(files) == set()


async def _grow_descendants(tenant_id: UUID, user_id: UUID, parent: UUID) -> None:
    async with _committed() as session:
        session.add_all(
            Files(
                name=f"page-{uuid4()}.png",
                mimetype="image/png",
                file_type=FileType.TEXT.value,
                owner_type="user",
                owner_user_id=user_id,
                owner_service_id=None,
                tenant_id=tenant_id,
                parent_file_id=parent,
            )
            for _ in range(100)
        )


async def _grow_references(tenant_id: UUID, user_id: UUID, parent: UUID) -> None:
    await _more_references(tenant_id, user_id, parent, 100)


@pytest.mark.parametrize(
    ("after_count", "grow", "listed"),
    [
        ("count_references", _grow_descendants, "file_family"),
        ("count_bound_transcripts", _grow_references, "FROM file_content_references"),
    ],
    ids=["descendants", "references"],
)
async def test_a_family_that_grew_after_it_was_counted_is_read_no_further(
    scope, monkeypatch, after_count, grow, listed
) -> None:
    tenant_id, user_id, _, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    # The derived file grows (the root is already locked by then).
    child = family[1][0]
    real = getattr(FlowFileFamilyRepository, after_count)
    grown: list[bool] = []

    async def count_then_grow(self, root_id, *, limit):
        counted = await real(self, root_id, limit=limit)
        if not grown:
            grown.append(True)
            await grow(tenant_id, user_id, child)
        return counted

    monkeypatch.setattr(FlowFileFamilyRepository, after_count, count_then_grow)
    async with _rows_returned() as statements:
        report = await _housekeeping()

    # Counted at two members and two references, never more than one row past
    # that is read or locked; the family waits for its next pass.
    assert report.blocked["abandoned_uploads.lock_deferred"] == 1
    assert (
        max(
            rows
            for statement, rows in statements
            if listed in statement and "count(*)" not in statement
        )
        <= 3
    )
    assert await _existing_files([f for f, _ in family]) == {f for f, _ in family}


async def test_a_call_selects_only_the_candidates_it_processes(scope) -> None:
    tenant_id, user_id, space_id, _ = scope
    held_flow_id = await _flow(tenant_id, user_id, space_id)
    async with _committed() as session:
        session.add_all(
            GallringReceipts(
                task=FLOWS_HOUSEKEEPING_TASK,
                entity_kind="file_family",
                entity_id=uuid4(),
                category="abandoned_upload",
                trigger="scheduled",
                tenant_id=tenant_id,
                flow_id=held_flow_id,
                phase="paused",
                paused_from_phase="pending",
                reason=ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE.value,
                started_at=_NOW + timedelta(seconds=index),
                updated_at=_NOW,
            )
            for index in range(6)
        )
        await _place_hold(session, tenant_id, held_flow_id)

    async with _rows_returned() as statements:
        report = await _housekeeping(chunk_rows=3, family_rows=50)

    # Three calls of three rows each; each receipt is selected (and locked)
    # exactly once, when it is processed.
    assert report.blocked["file_families.held"] == 6
    assert (
        sum(
            rows
            for statement, rows in statements
            if "FROM gallring_receipts" in statement
            and "ORDER BY gallring_receipts.started_at" in statement
        )
        == 6
    )


@pytest.mark.parametrize(("seconds", "families_per_chunk"), [(0.5, [1, 1]), (3.0, [2])])
async def test_family_gathering_respects_the_operator_time_budget(
    scope, test_settings, monkeypatch, seconds, families_per_chunk
) -> None:
    # M80: using a fixed gather time ignores the operator's transaction limit.
    from itertools import count
    from types import SimpleNamespace

    from eneo.flows.application import flow_housekeeping_task

    tenant_id, user_id, _, flow_id = scope
    for _ in range(2):
        await _abandoned_upload(tenant_id, user_id, flow_id, children=0)
    settings = test_settings.model_copy(
        update={"gallring_family_gather_seconds": seconds}
    )
    ticks = count(step=2)
    monkeypatch.setattr(flow_housekeeping_task, "get_settings", lambda: settings)
    monkeypatch.setattr(
        flow_housekeeping_task, "time", SimpleNamespace(monotonic=lambda: next(ticks))
    )

    report = await _housekeeping()

    assert report.counts["abandoned_uploads.families_completed"] == 2
    audits = await _gallring_audits(tenant_id)
    assert [
        audit.log_metadata["counts"]["families_completed"]
        for audit in audits
        if audit.log_metadata["step"] == "abandoned_uploads"
    ] == families_per_chunk


async def test_many_small_families_never_hold_the_gallring_lock_long(scope) -> None:
    tenant_id, user_id, _, flow_id = scope
    async with _committed() as session:
        await session.execute(
            sa.text(
                "WITH f AS (INSERT INTO files (id, name, mimetype, file_type, "
                "owner_type, owner_user_id, tenant_id) SELECT gen_random_uuid(), "
                "'x.txt', 'text/plain', 'text', 'user', :u, :t "
                "FROM generate_series(1, 400) RETURNING id) "
                "INSERT INTO flow_runtime_uploaded_files (file_id, flow_id, "
                "tenant_id, uploaded_for_step_id, owner_type, owner_user_id, "
                "created_at, updated_at) SELECT id, :f, :t, gen_random_uuid(), "
                "'user', :u, now() - interval '40 days', now() - interval '40 days' "
                "FROM f"
            ),
            {"t": tenant_id, "u": user_id, "f": flow_id},
        )
    stop = asyncio.Event()
    busy: list[float] = []

    async def hold_writer() -> None:
        # What placing or changing a legal hold does, over and over.
        while not stop.is_set():
            async with sessionmanager.session() as session, session.begin():
                started = time.monotonic()
                try:
                    await acquire_exclusive(session, GallringSubject.FLOW_HISTORY)
                except GallringLockBusy:
                    busy.append(time.monotonic() - started)
            await asyncio.sleep(0.05)

    writer = asyncio.create_task(hold_writer())
    try:
        report = await _housekeeping(chunk_rows=2000)
    finally:
        stop.set()
        await writer

    # Even at the largest chunk size a call gathers families for at most a
    # second, so a hold change never waits out the lock's five seconds.
    assert busy == []
    assert report.counts["abandoned_uploads.families_completed"] == 400


async def test_a_child_added_while_the_family_is_locked_defers_only_that_family(
    scope, monkeypatch
) -> None:
    tenant_id, user_id, _, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    unbound = await _transcript(tenant_id, user_id, flow_id, created_days_ago=40)
    real_scalars = AsyncSession.scalars
    added: list[UUID] = []

    async def scalars(self, statement, *args, **kwargs):
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        if "FOR UPDATE OF files SKIP LOCKED" in compiled and not added:
            # A child committed after the family was enumerated, before its lock.
            added.append(
                (await _file(tenant_id, user_id, parent_file_id=family[1][0]))[0]
            )
        return await real_scalars(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalars", scalars)
    report = await _housekeeping()
    monkeypatch.undo()

    # The night goes on: the family waits, the next step still runs.
    assert report.outcome == GallringJobOutcome.SUCCEEDED
    assert report.blocked["abandoned_uploads.lock_deferred"] == 1
    assert report.counts["live_transcripts.transcripts_deleted"] == 1
    assert await _existing_files([*(f for f, _ in family), *added]) == {
        *(f for f, _ in family),
        *added,
    }
    assert (
        await _scalar(
            sa.select(FlowLiveTranscripts.id).where(FlowLiveTranscripts.id == unbound)
        )
        is None
    )


async def test_a_family_of_401_files_is_reclaimed_in_one_transaction(scope) -> None:
    tenant_id, user_id, _, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id)
    root = family[0][0]
    async with _committed() as session:
        session.add_all(
            Files(
                name=f"page-{uuid4()}.png",
                mimetype="image/png",
                file_type=FileType.TEXT.value,
                owner_type="user",
                owner_user_id=user_id,
                owner_service_id=None,
                tenant_id=tenant_id,
                parent_file_id=root,
            )
            for _ in range(400)
        )
    async with _committed() as session:
        await session.execute(
            sa.text(
                "INSERT INTO flow_live_transcripts (tenant_id, user_id, flow_id, "
                "flow_version, step_id, model_id, recording_id, text, "
                "received_audio_seconds, created_at, bound_file_id) "
                "SELECT :t, :u, :f, 1, gen_random_uuid(), gen_random_uuid(), "
                "'recording', 'text', 1, now(), :b FROM generate_series(1, 100)"
            ),
            {"t": tenant_id, "u": user_id, "f": flow_id, "b": root},
        )

    report = await _housekeeping()

    assert report.outcome == GallringJobOutcome.SUCCEEDED
    [audit] = [
        audit
        for audit in await _gallring_audits(tenant_id)
        if audit.log_metadata["step"] == "abandoned_uploads"
    ]
    # Every member checked, the bound transcripts and every file in one batch.
    assert audit.log_metadata["counts"] == {
        "members_checked": 401,
        "manifest_items": 1,
        "anchors_released": 1,
        "transcripts_deleted": 100,
        "references_released": 1,
        "files_deleted": 401,
        "families_completed": 1,
    }
    assert await _existing_files([root]) == set()


async def test_a_receipt_being_pruned_no_longer_covers_its_root(scope) -> None:
    tenant_id = scope[0]
    covered, withdrawn = uuid4(), uuid4()
    async with _committed() as session:
        session.add_all(
            GallringReceipts(
                task=FLOWS_HOUSEKEEPING_TASK,
                entity_kind="file_family",
                entity_id=root,
                category="abandoned_upload",
                trigger="scheduled",
                tenant_id=tenant_id,
                phase="pending",
                started_at=_NOW,
                updated_at=_NOW,
                pruning_started_at=pruning_started_at,
            )
            for root, pruning_started_at in ((covered, None), (withdrawn, _NOW))
        )

    async with _committed() as session:
        recorded = await FlowHousekeepingRepository(session).recorded_families(
            task=FLOWS_HOUSEKEEPING_TASK,
            category=GallringCategory.ABANDONED_UPLOAD,
            root_ids=[covered, withdrawn],
        )

    assert recorded == {covered}


# Housekeeping deleters ---------------------------------------------------------


async def test_each_deleter_is_bounded_and_audited_once_per_batch(scope) -> None:
    tenant_id, user_id, space_id, flow_id = scope
    for _ in range(3):
        await _abandoned_upload(tenant_id, user_id, flow_id)
        await _transcript(tenant_id, user_id, flow_id, created_days_ago=40)
        await _delivered_outbox_row(tenant_id, user_id, flow_id)

    # Two rows per chunk: families of one file (8 examined rows) go one per
    # batch however high the cap, which only lets a single family start a batch.
    report = await _housekeeping(chunk_rows=2, family_rows=50)

    assert report.outcome == GallringJobOutcome.SUCCEEDED
    audits = await _gallring_audits(tenant_id)
    removed = {
        "abandoned_uploads": ("families_completed", 3),
        "live_transcripts": ("transcripts_deleted", 2),
        "audit_outbox": ("outbox_rows_deleted", 2),
    }
    for step, (key, least) in removed.items():
        step_audits = [a for a in audits if a.log_metadata["step"] == step]
        assert sum(a.log_metadata["counts"].get(key, 0) for a in step_audits) == 3, step
        # A backlog larger than a chunk needs several batches, each audited once.
        batches = [a.log_metadata["batch_seq"] for a in step_audits]
        assert len(batches) == len(set(batches)) >= least, step
        for audit in step_audits:
            assert audit.id == gallring_batch_audit_id(
                job_run_id=report.job_run_id,
                batch_seq=audit.log_metadata["batch_seq"],
                tenant_id=tenant_id,
            )
    async with _committed() as session:
        for table in (
            FlowRuntimeUploadedFiles,
            FlowLiveTranscripts,
            FlowRunAuditOutbox,
        ):
            assert (
                await session.scalar(sa.select(sa.func.count()).select_from(table)) == 0
            )


async def test_the_current_window_applies_to_existing_transcripts_and_uploads(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    bound_file_id, _ = await _file(tenant_id, user_id)
    ten_days = await _transcript(tenant_id, user_id, flow_id, created_days_ago=10)
    five_days = await _transcript(tenant_id, user_id, flow_id, created_days_ago=5)
    bound = await _transcript(
        tenant_id, user_id, flow_id, created_days_ago=40, bound_file_id=bound_file_id
    )
    upload = await _abandoned_upload(tenant_id, user_id, flow_id)  # 40 days old
    await _age_upload(upload[0][0], days=10)

    await _housekeeping()  # the 30-day default keeps everything

    async with _committed() as session:
        kept = set(await session.scalars(sa.select(FlowLiveTranscripts.id)))
    assert kept == {ten_days, five_days, bound}
    assert await _existing_files([upload[0][0]]) == {upload[0][0]}

    # Shortening the window applies to the items that already exist.
    async with _committed() as session:
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(flow_runtime_upload_abandonment_days=7)
        )
    await _housekeeping()

    async with _committed() as session:
        kept = set(await session.scalars(sa.select(FlowLiveTranscripts.id)))
    assert kept == {five_days, bound}
    assert await _existing_files([upload[0][0]]) == set()


# Health -------------------------------------------------------------------------


async def test_health_flags_a_task_without_a_recent_completion() -> None:
    policy = build_flow_runtime_health_policy(
        task_timeout_seconds=3600, gallring_tasks=(FLOWS_HOUSEKEEPING_TASK,)
    )

    async def stale_tasks() -> tuple[str, ...]:
        async with _committed() as session:
            snapshot = await load_flow_runtime_health_snapshot(
                session=session, now=datetime.now(timezone.utc), policy=policy
            )
        return snapshot.stale_gallring_tasks

    async def execution(outcome: GallringJobOutcome, *, hours_ago: int) -> None:
        async with _committed() as session:
            at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
            session.add(
                GallringJobRuns(
                    task=FLOWS_HOUSEKEEPING_TASK,
                    outcome=outcome.value,
                    started_at=at,
                    heartbeat_at=at,
                    finished_at=at,
                )
            )

    assert await stale_tasks() == ()  # never ran
    await execution(GallringJobOutcome.FAILED, hours_ago=72)
    assert await stale_tasks() == (FLOWS_HOUSEKEEPING_TASK,)
    await execution(GallringJobOutcome.SUCCEEDED, hours_ago=60)
    assert await stale_tasks() == (FLOWS_HOUSEKEEPING_TASK,)
    await execution(GallringJobOutcome.PARTIAL, hours_ago=1)
    assert await stale_tasks() == ()


# Proof without content ----------------------------------------------------------

_AUDIT_METADATA_KEYS = frozenset(
    {
        "task",
        "step",
        "job_run_id",
        "batch_seq",
        "counts",
        "blocked",
        "receipt_ids",
        "reason",
        "actor",
    }
)


async def test_proof_rows_and_audits_hold_no_content_or_digest(scope) -> None:
    tenant_id, user_id, _, flow_id = scope
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=1)
    file_ids = [file_id for file_id, _ in family]
    content_ids = [content_id for _, content_id in family]
    async with _committed() as session:
        names = list(
            await session.scalars(sa.select(Files.name).where(Files.id.in_(file_ids)))
        )
        payloads = list(
            await session.scalars(
                sa.select(InlineContentPayloads.payload).where(
                    InlineContentPayloads.content_id.in_(content_ids)
                )
            )
        )
        digests = list(
            await session.scalars(
                sa.select(ObjectContents.sha256).where(
                    ObjectContents.id.in_(content_ids)
                )
            )
        )
    async with sessionmanager.session() as session:
        await _runner(session).skip(FLOWS_HOUSEKEEPING_TASK)

    await _housekeeping()

    async with _committed() as session:
        proof_rows = [
            dict(row._mapping)
            for table in (GallringJobRuns, GallringReceipts, GallringReceiptItems)
            for row in await session.execute(sa.select(table.__table__))
        ]
    audits = await _gallring_audits(tenant_id)
    assert proof_rows and audits
    for audit in audits:
        assert set(audit.log_metadata) <= _AUDIT_METADATA_KEYS
    recorded = repr(proof_rows) + repr(
        [(audit.description, audit.log_metadata) for audit in audits]
    )
    forbidden = [
        *names,
        *(payload.hex() for payload in payloads),
        *(repr(payload) for payload in payloads),
        *(digest.hex() for digest in digests),
        *(repr(digest) for digest in digests),
    ]
    for value in forbidden:
        assert value not in recorded


async def test_final_receipts_and_job_runs_are_pruned_after_audit_retention(
    scope,
) -> None:
    tenant_id, *_ = scope
    old = _NOW - timedelta(days=400)  # past the 365-day default audit retention
    async with _committed() as session:
        final = GallringReceipts(
            task=FLOWS_HOUSEKEEPING_TASK,
            entity_kind="file_family",
            entity_id=uuid4(),
            category="abandoned_upload",
            trigger="scheduled",
            tenant_id=tenant_id,
            phase="completed",
            started_at=old,
            updated_at=old,
            manifest_completed_at=old,
            completed_at=old,
        )
        # Another task's unfinished receipt: pruning never removes it by age.
        unfinished = GallringReceipts(
            task="tests.other",
            entity_kind="file_family",
            entity_id=uuid4(),
            category="abandoned_upload",
            trigger="scheduled",
            tenant_id=tenant_id,
            phase="paused",
            paused_from_phase="deleting",
            reason=ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE.value,
            started_at=old,
            updated_at=old,
            manifest_completed_at=old,
        )
        old_run = GallringJobRuns(
            task=FLOWS_HOUSEKEEPING_TASK,
            outcome=GallringJobOutcome.SUCCEEDED.value,
            started_at=old,
            heartbeat_at=old,
            finished_at=old,
        )
        recent = _NOW - timedelta(days=10)
        recent_final = GallringReceipts(
            task=FLOWS_HOUSEKEEPING_TASK,
            entity_kind="file_family",
            entity_id=uuid4(),
            category="abandoned_upload",
            trigger="scheduled",
            tenant_id=tenant_id,
            phase="completed",
            started_at=recent,
            updated_at=recent,
            manifest_completed_at=recent,
            completed_at=recent,
        )
        session.add_all([final, unfinished, recent_final, old_run])
        await session.flush()
        final_id, unfinished_id, old_run_id = final.id, unfinished.id, old_run.id
        recent_id = recent_final.id

    report = await _housekeeping()

    async with _committed() as session:
        assert await session.get(GallringReceipts, final_id) is None
        assert await session.get(GallringReceipts, unfinished_id) is not None
        assert await session.get(GallringReceipts, recent_id) is not None
        assert await session.get(GallringJobRuns, old_run_id) is None
        assert await session.get(GallringJobRuns, report.job_run_id) is not None
    # One chunk marks the expired receipt, the next deletes it; both audited.
    assert [
        audit.log_metadata["counts"]
        for audit in await _gallring_audits(tenant_id)
        if audit.log_metadata["step"] == "prune_receipts"
    ] == [{"receipts_marked": 1}, {"receipts_pruned": 1}]


async def test_receipt_pruning_keeps_the_proof_of_a_held_flow(scope) -> None:
    tenant_id, _, _, held_flow_id = scope
    old = _NOW - timedelta(days=400)  # past the 365-day default audit retention

    def receipt(**values: Any) -> GallringReceipts:
        return GallringReceipts(
            task=FLOWS_HOUSEKEEPING_TASK,
            entity_kind="file_family",
            entity_id=uuid4(),
            category="abandoned_upload",
            trigger="scheduled",
            tenant_id=tenant_id,
            started_at=old,
            updated_at=old,
            **values,
        )

    async with _committed() as session:
        expired = receipt(
            flow_id=held_flow_id,
            phase="completed",
            manifest_completed_at=old,
            completed_at=old,
        )
        # Marked before the hold was placed: its remaining items stay too.
        marked = receipt(flow_id=held_flow_id, phase="pending", pruning_started_at=old)
        unheld = receipt(phase="completed", manifest_completed_at=old, completed_at=old)
        session.add_all([expired, marked, unheld])
        await session.flush()
        session.add(
            GallringReceiptItems(
                receipt_id=marked.id, file_id=uuid4(), content_id=uuid4()
            )
        )
        ids = {"expired": expired.id, "marked": marked.id, "unheld": unheld.id}
        await _place_hold(session, tenant_id, held_flow_id)

    await _housekeeping()

    async with _committed() as session:
        kept = {
            name
            for name, receipt_id in ids.items()
            if await session.get(GallringReceipts, receipt_id) is not None
        }
        items = await session.scalar(
            sa.select(sa.func.count()).where(
                GallringReceiptItems.receipt_id == ids["marked"]
            )
        )
    assert kept == {"expired", "marked"}
    assert items == 1


async def test_housekeeping_deletes_no_data_a_hold_covers(scope) -> None:
    tenant_id, user_id, space_id, held_flow_id = scope
    free_flow_id = await _flow(tenant_id, user_id, space_id)
    run_held_flow_id = await _flow(tenant_id, user_id, space_id)
    family = await _abandoned_upload(tenant_id, user_id, held_flow_id)
    held_transcript = await _transcript(
        tenant_id, user_id, held_flow_id, created_days_ago=40
    )
    free_transcript = await _transcript(
        tenant_id, user_id, free_flow_id, created_days_ago=40
    )
    outbox_id = await _delivered_outbox_row(tenant_id, user_id, held_flow_id)
    # A run hold covers its run's outbox mirror, not the flow's run-less data.
    run_held_outbox_id = await _delivered_outbox_row(
        tenant_id, user_id, run_held_flow_id
    )
    run_held_flow_transcript = await _transcript(
        tenant_id, user_id, run_held_flow_id, created_days_ago=40
    )
    async with _committed() as session:
        mirror = await session.get(FlowRunAuditOutbox, run_held_outbox_id)
        assert mirror is not None and mirror.flow_run_id is not None
        await _place_hold(session, tenant_id, held_flow_id)
        await _place_hold(
            session, tenant_id, run_held_flow_id, run_id=mirror.flow_run_id
        )

    report = await _housekeeping()

    assert await _existing_files([family[0][0]]) == {family[0][0]}
    async with _committed() as session:
        assert await session.get(FlowLiveTranscripts, held_transcript) is not None
        assert await session.get(FlowLiveTranscripts, free_transcript) is None
        assert await session.get(FlowRunAuditOutbox, outbox_id) is not None
        assert await session.get(FlowRunAuditOutbox, run_held_outbox_id) is not None
        assert await session.get(FlowLiveTranscripts, run_held_flow_transcript) is None
    assert report.blocked == {
        "abandoned_uploads.held": 1,
        "live_transcripts.held": 1,
        "audit_outbox.held": 2,
    }


async def test_the_administrator_purge_keeps_unbound_transcripts_a_hold_covers(
    scope,
) -> None:
    tenant_id, user_id, space_id, held_flow_id = scope
    free_flow_id = await _flow(tenant_id, user_id, space_id)
    held = await _transcript(tenant_id, user_id, held_flow_id, created_days_ago=40)
    free = await _transcript(tenant_id, user_id, free_flow_id, created_days_ago=40)
    async with _committed() as session:
        await _place_hold(session, tenant_id, held_flow_id)

    async with _committed() as session:
        repository = LiveTranscriptRepository(session)
        preview = await repository.delete_expired_unbound(
            tenant_id=tenant_id, now=_NOW, limit=10, dry_run=True
        )
        purged = await repository.delete_expired_unbound(
            tenant_id=tenant_id, now=_NOW, limit=10, dry_run=False
        )

    assert (preview.candidate_count, purged.purged_count) == (1, 1)
    async with _committed() as session:
        assert await session.get(FlowLiveTranscripts, held) is not None
        assert await session.get(FlowLiveTranscripts, free) is None


async def test_a_hold_committed_while_a_chunk_waits_to_select_is_honoured(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    transcript = await _transcript(tenant_id, user_id, flow_id, created_days_ago=40)

    async with sessionmanager.session() as placer, placer.begin():
        await _place_hold(placer, tenant_id, flow_id)
        running = asyncio.create_task(_housekeeping())
        # The chunk waits for the hold's transaction before it selects anything.
        await _until_a_session_waits_on_the_flow_history_lock()
    report = await running

    assert (
        await _scalar(
            sa.select(FlowLiveTranscripts.id).where(
                FlowLiveTranscripts.id == transcript
            )
        )
        == transcript
    )
    assert report.blocked.get("live_transcripts.held") == 1


# Exact scenarios from the pre-gate review ----------------------------------------


async def test_deletable_outbox_mirrors_are_found_past_young_and_pending_rows(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    # 30 rows with the lowest ids are not deletable (pending or recent).
    for index in range(30):
        row_id = await _delivered_outbox_row(tenant_id, user_id, flow_id)
        async with _committed() as session:
            await session.execute(
                sa.update(FlowRunAuditOutbox)
                .where(FlowRunAuditOutbox.id == row_id)
                .values(
                    id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
                    delivery_status=(
                        FlowOutboxDeliveryStatus.PENDING.value
                        if index % 2
                        else FlowOutboxDeliveryStatus.DELIVERED.value
                    ),
                    delivered_at=None if index % 2 else _NOW,
                )
            )
    deletable = await _delivered_outbox_row(tenant_id, user_id, flow_id)

    report = await _housekeeping(chunk_rows=5, budget_rows=20)

    assert report.counts["audit_outbox.outbox_rows_deleted"] == 1
    async with _committed() as session:
        assert await session.get(FlowRunAuditOutbox, deletable) is None
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(FlowRunAuditOutbox)
        )
    assert remaining == 30


async def test_the_outbox_selection_skips_mirrors_whose_audit_log_exists(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    retained = [
        await _delivered_outbox_row(tenant_id, user_id, flow_id) for _ in range(3)
    ]
    async with _committed() as session:
        for index, mirror_id in enumerate(retained):
            mirror = await session.get(FlowRunAuditOutbox, mirror_id)
            assert mirror is not None
            # Older than the deletable mirror, and its audit log still exists.
            mirror.delivered_at = _NOW - timedelta(days=500 + index)
            session.add(
                AuditLogTable(
                    id=mirror_id,
                    tenant_id=tenant_id,
                    actor_id=user_id,
                    actor_type="user",
                    action="flow_run_completed",
                    entity_type="flow_run",
                    entity_id=mirror.entity_id,
                    timestamp=_NOW,
                    description="Flow run completed by executor_completed.",
                    log_metadata={},
                    outcome="success",
                )
            )
    deletable = await _delivered_outbox_row(tenant_id, user_id, flow_id)

    async with _committed() as session:
        page = await FlowHousekeepingRepository(session).deletable_audit_outbox(
            now=_NOW, after=None, limit=2
        )

    assert [row.id for row in page] == [deletable]


async def test_a_discovery_pass_continues_across_nightly_executions(scope) -> None:
    tenant_id, user_id, space_id, held_flow_id = scope
    free_flow_id = await _flow(tenant_id, user_id, space_id)
    # A held prefix of three transcripts, larger than one night's two-row budget.
    held = [
        await _transcript(tenant_id, user_id, held_flow_id, created_days_ago=age)
        for age in (45, 44, 43)
    ]
    free = await _transcript(tenant_id, user_id, free_flow_id, created_days_ago=41)
    async with _committed() as session:
        await _place_hold(session, tenant_id, held_flow_id)

    first = await _housekeeping(chunk_rows=2, budget_rows=2)
    second = await _housekeeping(chunk_rows=2, budget_rows=2)

    assert first.outcome == GallringJobOutcome.PARTIAL
    assert first.blocked == {"live_transcripts.held": 2}
    # The second night continues after the prefix and reaches the free transcript.
    assert second.blocked == {"live_transcripts.held": 1}
    assert second.counts == {"live_transcripts.transcripts_deleted": 1}
    async with _committed() as session:
        assert await session.get(FlowLiveTranscripts, free) is None
        for transcript_id in held:
            assert await session.get(FlowLiveTranscripts, transcript_id) is not None


async def test_a_family_deeper_than_the_traversal_is_never_reported_reclaimed(
    scope,
) -> None:
    tenant_id, user_id, _, flow_id = scope
    # A root and a chain of 33 derived files: one level beyond the traversal.
    family = await _abandoned_upload(tenant_id, user_id, flow_id, children=33)
    file_ids = [file_id for file_id, _ in family]

    report = await _housekeeping()

    receipt = await _receipt(file_ids[0])
    assert (receipt.phase, receipt.reason) == (
        ReceiptPhase.PAUSED.value,
        ReceiptReason.FAMILY_DEPTH_EXCEEDED.value,
    )
    assert report.blocked["abandoned_uploads.family_depth_exceeded"] == 1
    assert await _existing_files(file_ids) == set(file_ids)
    assert (
        await _scalar(
            sa.select(FlowRuntimeUploadedFiles.file_id).where(
                FlowRuntimeUploadedFiles.file_id == file_ids[0]
            )
        )
        == file_ids[0]
    )


async def test_the_outbox_selection_ranges_over_the_delivered_index(scope) -> None:
    tenant_id, user_id, _, flow_id = scope
    async with _committed() as session:
        # 20 000 delivered mirrors, a quarter past the 365-day audit retention.
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text(
                "INSERT INTO flow_run_audit_outbox (id, tenant_id, flow_id, "
                "flow_run_id, run_revision, description, action, entity_type, "
                "entity_id, actor_id, actor_type, source, target_status, "
                "delivery_status, delivery_attempts, delivered_at, created_at, "
                "updated_at) SELECT gen_random_uuid(), :t, :f, r, 1, "
                "'flow_run_completed:executor_completed', "
                "'flow_run_completed', 'flow_run', r, :u, 'user', "
                "'executor_completed', 'completed', 'delivered', 1, "
                "now() - make_interval(days => g % 500), now(), now() "
                "FROM (SELECT gen_random_uuid() AS r, g "
                "FROM generate_series(1, 20000) g) runs"
            ),
            {"t": tenant_id, "f": flow_id, "u": user_id},
        )
    async with _committed() as session:
        await session.execute(sa.text("ANALYZE flow_run_audit_outbox"))

    selects: list[tuple[str, Any]] = []
    engine = sessionmanager._engine  # noqa: SLF001
    assert engine is not None

    def keep(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append((statement, parameters))

    async with _committed() as session:
        event.listen(engine.sync_engine, "before_cursor_execute", keep)
        try:
            page = await FlowHousekeepingRepository(session).deletable_audit_outbox(
                now=_NOW, after=None, limit=500
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", keep)
        statement, parameters = selects[0]
        connection = await session.connection()
        plan = "\n".join(
            row[0]
            for row in await connection.exec_driver_sql(
                "EXPLAIN ANALYZE " + statement, parameters
            )
        )

    assert len(page) == 500
    assert all(row.delivered_at < _NOW - timedelta(days=365) for row in page)
    assert "ix_flow_run_audit_outbox_delivered" in plan
    assert "Rows Removed by Filter" not in plan
