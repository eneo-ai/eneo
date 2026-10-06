"""The flows.history task (auto_delete) and the explicit purge against PostgreSQL.

Every test commits its fixtures, because the runner commits chunk by chunk in
its own sessions, and observes the effect through fresh sessions. Each test
names the mutants it kills.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.data_retention.domain.retention import (
    ReceiptPhase,
    RetentionJobOutcome,
    RetentionTrigger,
)
from eneo.data_retention.infrastructure.retention_lock import (
    RetentionLockBusy,
    RetentionSubject,
    acquire_exclusive,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowProviderCalls,
    FlowRetentionHolds,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpointEdits,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    Flows,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowStepTranscriptSources,
    FlowStepTranscriptWords,
    FlowTranscriptCorrectionRevisions,
    FlowTranscriptCorrections,
    FlowVersions,
)
from eneo.database.tables.retention_tables import (
    RetentionJobRuns,
    RetentionReceiptItems,
    RetentionReceipts,
)
from eneo.flows.application.flow_run_history_deletion import (
    SCHEDULED_MODES,
    FlowRunHistoryDeletion,
    PurgeScope,
)
from eneo.flows.application.flow_run_history_purge import FlowRunHistoryExplicitPurge
from eneo.flows.application.flow_run_history_retention_task import (
    FlowRunHistoryRetentionTask,
)
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK
from eneo.flows.infrastructure.flow_run_deletion_repo import (
    FLOW_RUN_CHILD_TABLES,
    FlowRunDeletionRepository,
)
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FlowRunHistoryDueRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.main.config import get_settings
from tests.integration.flows.flow_run_deletion_support import delete_run, purge
from tests.integration.flows.test_flow_gallring import (
    _committed,
    _file,
    _flow,
    _place_hold,
    _runner,
    _space,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

OLD = datetime.now(timezone.utc) - timedelta(days=3)


@pytest.fixture(autouse=True)
def row_budget_not_wall_clock(monkeypatch):
    monkeypatch.setattr(get_settings(), "gallring_family_gather_seconds", 60.0)


async def _auto_delete(flow_id: UUID, days: int = 1, mode: str = "auto_delete") -> None:
    async with _committed() as session:
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(
                flow_run_history_retention_mode=mode,
                flow_run_history_retention_days=days,
            )
        )


async def _version(session, tenant_id: UUID, flow_id: UUID) -> None:
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
                definition_checksum=f"history-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
            )
        )
        await session.flush()


async def _bare_run(
    tenant_id: UUID,
    user_id: UUID,
    flow_id: UUID,
    *,
    at: datetime = OLD,
    run_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> UUID:
    async with _committed() as session:
        await _version(session, tenant_id, flow_id)
        run = FlowRuns(
            id=run_id or uuid4(),
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=user_id,
            tenant_id=tenant_id,
            trace_id=uuid4(),
            idempotency_key=idempotency_key,
            status="completed",
            started_at=at,
            finished_at=at,
            created_at=at,
            updated_at=at,
        )
        session.add(run)
        await session.flush()
        return run.id


class Loaded:
    def __init__(self, run_id: UUID, files: dict[str, UUID], transcript: UUID) -> None:
        self.run_id = run_id
        self.files = files
        self.transcript = transcript


async def _loaded_run(
    tenant_id: UUID,
    user_id: UUID,
    flow_id: UUID,
    *,
    attempts: int = 1,
    idempotency_key: str | None = None,
) -> Loaded:
    """A run with a row in every table below flow_runs, a generated file with a
    derived child and a runtime upload with its binding and a bound transcript."""
    generated, _ = await _file(tenant_id, user_id)
    derived, _ = await _file(tenant_id, user_id, parent_file_id=generated)
    upload, _ = await _file(tenant_id, user_id)
    run_id = await _bare_run(
        tenant_id, user_id, flow_id, idempotency_key=idempotency_key
    )
    step_id = uuid4()
    async with _committed() as session:
        session.add(
            FlowRuntimeUploadedFiles(
                file_id=upload,
                flow_id=flow_id,
                tenant_id=tenant_id,
                uploaded_for_step_id=step_id,
                owner_type="user",
                owner_user_id=user_id,
                owner_service_id=None,
                created_at=OLD,
                updated_at=OLD,
            )
        )
        result = FlowStepResults(
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=step_id,
            step_order=1,
            status="completed",
            num_tokens_input=1,
            num_tokens_output=1,
            started_at=OLD,
            finished_at=OLD,
        )
        session.add(result)
        await session.flush()
        attempt_ids = []
        for attempt_no in range(1, attempts + 1):
            attempt = FlowStepAttempts(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=1,
                attempt_no=attempt_no,
                status="completed",
                started_at=OLD,
                finished_at=OLD,
            )
            session.add(attempt)
            await session.flush()
            attempt_ids.append(attempt.id)
            session.add(
                FlowStepAttemptResolvedInputs(
                    flow_step_attempt_id=attempt.id,
                    resolved_input_edges_jsonb={"schema_version": 1, "edges": []},
                )
            )
            await session.flush()
            session.add(
                FlowProviderCalls(
                    flow_step_attempt_id=attempt.id,
                    resolved_inputs_attempt_id=attempt.id,
                    call_kind="completion",
                    ordinal=1,
                    status="started",
                    request_schema_version=2,
                    provider_request_hash="a" * 64,
                    requested_model="model",
                    provider="provider",
                    response_format="none",
                    requested_capabilities=[],
                    resolved_input_edge_indexes=[],
                    call_reason="initial",
                    requested_at=OLD,
                )
            )
        session.add_all(
            [
                FlowRunStepResultFiles(
                    flow_run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_result_id=result.id,
                    step_id=step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=generated,
                    ordinal=0,
                    source="declared_artifact",
                ),
                FlowRunStepInputFiles(
                    flow_run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=upload,
                    ordinal=0,
                ),
                FlowStepTranscriptWords(
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                    flow_run_id=run_id,
                    step_id=step_id,
                    segments_hash="b" * 64,
                    words_json=[],
                ),
                FlowStepTranscriptSources(
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                    flow_run_id=run_id,
                    step_id=step_id,
                    attempt_no=1,
                    segments_bytes=0,
                    detail_bytes=0,
                    words_bytes=0,
                    segments_count=0,
                    words_count=0,
                ),
            ]
        )
        corrections = FlowTranscriptCorrections(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            step_id=step_id,
            occurrences_json=[],
            speaker_edits_json=[],
            segments_hash="c" * 64,
            edited_by_principal_type="user",
            edited_by_user_id=user_id,
        )
        session.add(corrections)
        await session.flush()
        revision = FlowTranscriptCorrectionRevisions(
            tenant_id=tenant_id,
            correction_set_id=corrections.id,
            flow_id=flow_id,
            flow_run_id=run_id,
            step_id=step_id,
            revision=1,
            occurrences_json=[],
            speaker_edits_json=[],
            segments_hash="c" * 64,
            edited_by_principal_type="user",
            edited_by_user_id=user_id,
        )
        session.add(revision)
        checkpoint = FlowRunReviewCheckpoints(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            state="resumed",
            revision=1,
            schema_version=1,
            original_payload_json={"text": "a"},
            current_payload_json={"text": "b"},
            step_label="Review",
            review_mode="edit",
            output_type="text",
            requester_user_id=user_id,
            requester_principal_type="user",
            decided_by_user_id=user_id,
            decided_by_principal_type="user",
            next_step_ids_json=[],
            resume_idempotency_key=f"resume-{uuid4()}",
            edited_at=OLD,
            approved_at=OLD,
            resumed_at=OLD,
        )
        session.add(checkpoint)
        await session.flush()
        session.add(
            FlowRunReviewCheckpointEdits(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=run_id,
                checkpoint_id=checkpoint.id,
                revision=1,
                cause="corrections_folded",
                corrections_revision_id=revision.id,
                payload_json={"text": "b"},
                payload_sha256_before="d" * 64,
                payload_sha256_after="e" * 64,
                edited_by_principal_type="user",
                edited_by_user_id=user_id,
            )
        )
        session.add(
            FlowRunWebhookDeliveries(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=run_id,
                step_id=step_id,
                step_order=1,
                attempt_no=1,
                idempotency_key=f"{run_id}:1:webhook",
                payload_ref="step_output",
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                delivery_attempts=1,
                delivered_at=OLD,
            )
        )
        session.add(
            FlowRunAuditOutbox(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=run_id,
                run_revision=1,
                description="flow_run_completed:executor_completed",
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=run_id,
                actor_id=user_id,
                actor_type="user",
                source="executor_completed",
                target_status="completed",
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                delivery_attempts=1,
                delivered_at=OLD,
            )
        )
        transcript = FlowLiveTranscripts(
            tenant_id=tenant_id,
            user_id=user_id,
            flow_id=flow_id,
            flow_version=1,
            step_id=step_id,
            model_id=uuid4(),
            recording_id=f"rec-{uuid4().hex[:8]}",
            text="Spoken words.",
            segments=None,
            received_audio_seconds=1.0,
            bound_file_id=upload,
        )
        session.add(transcript)
        await session.flush()
        transcript_id = transcript.id
    return Loaded(
        run_id,
        {"generated": generated, "derived": derived, "upload": upload},
        transcript_id,
    )


async def _history(**limits: Any) -> RetentionRunReport:
    family_rows = limits.pop("family_rows", None)
    async with sessionmanager.session() as session:
        task = FlowRunHistoryRetentionTask(session, family_rows=family_rows)
        return await _runner(session, **limits).run(task)


async def _rows_below(run_id: UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with _committed() as session:
        for table, of_run in FLOW_RUN_CHILD_TABLES:
            counts[table.__tablename__] = int(
                await session.scalar(
                    sa.select(sa.func.count()).select_from(table).where(of_run(run_id))
                )
                or 0
            )
    return counts


async def _fence(run_id: UUID) -> UUID | None:
    async with _committed() as session:
        return await session.scalar(
            sa.select(FlowRuns.retention_receipt_id).where(FlowRuns.id == run_id)
        )


async def _run_exists(run_id: UUID) -> bool:
    async with _committed() as session:
        return await session.get(FlowRuns, run_id) is not None


async def _receipt_of(run_id: UUID) -> RetentionReceipts:
    async with _committed() as session:
        receipt = await session.scalar(
            sa.select(RetentionReceipts).where(
                RetentionReceipts.task == FLOWS_HISTORY_TASK,
                RetentionReceipts.entity_id == run_id,
            )
        )
        assert receipt is not None
        session.expunge(receipt)
        return receipt


async def _files_exist(*file_ids: UUID) -> set[UUID]:
    from eneo.database.tables.files_table import Files

    async with _committed() as session:
        return set(
            await session.scalars(sa.select(Files.id).where(Files.id.in_(file_ids)))
        )


@pytest.fixture
async def scope(test_tenant, admin_user) -> tuple[UUID, UUID, UUID, UUID]:
    space_id = await _space(test_tenant.id, admin_user.id)
    flow_id = await _flow(test_tenant.id, admin_user.id, space_id)
    await _auto_delete(flow_id)
    return test_tenant.id, admin_user.id, space_id, flow_id


# The whole run ------------------------------------------------------------------


async def test_the_nightly_task_deletes_a_fully_loaded_run_with_its_files(scope):
    """Mutants M107 manifest_after_release, children_in_reverse_order, no_audit_effects."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id)
    assert all(await _rows_below(loaded.run_id))  # every child table has a row

    # A database observer rejects reference removal before every family pair
    # is recorded, even if the deletion would commit all its work together.
    guard = f"test_manifest_{loaded.run_id.hex}"
    link_tables = (FlowRunStepInputFiles, FlowRunStepResultFiles)
    async with _committed() as session:
        await session.execute(
            sa.text(
                f"""CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF EXISTS (
                        WITH RECURSIVE family AS (
                            SELECT id FROM files WHERE id = OLD.file_id
                            UNION ALL
                            SELECT child.id FROM files child
                            JOIN family parent ON child.parent_file_id = parent.id
                        )
                        SELECT 1 FROM file_content_references content
                        JOIN family ON family.id = content.file_id
                        WHERE NOT EXISTS (
                            SELECT 1 FROM {RetentionReceiptItems.__tablename__} item
                            JOIN flow_runs run ON run.gallring_receipt_id = item.receipt_id
                            WHERE run.id = OLD.flow_run_id
                            AND item.file_id = content.file_id
                            AND item.content_id = content.content_id
                        )
                    ) THEN
                        RAISE EXCEPTION 'Family manifest missing before link release';
                    END IF;
                    RETURN OLD;
                END $$"""
            )
        )
        for table in link_tables:
            await session.execute(
                sa.text(
                    f"CREATE TRIGGER {guard} BEFORE DELETE ON {table.__tablename__} "
                    f"FOR EACH ROW WHEN (OLD.flow_run_id = '{loaded.run_id}'::uuid) "
                    f"EXECUTE FUNCTION {guard}()"
                )
            )
    try:
        report = await _history()
    finally:
        async with _committed() as session:
            for table in link_tables:
                await session.execute(
                    sa.text(f"DROP TRIGGER {guard} ON {table.__tablename__}")
                )
            await session.execute(sa.text(f"DROP FUNCTION {guard}()"))

    assert report.outcome == RetentionJobOutcome.SUCCEEDED, report
    assert not await _run_exists(loaded.run_id)
    assert set((await _rows_below(loaded.run_id)).values()) == {0}
    assert await _files_exist(*loaded.files.values()) == set()
    async with _committed() as session:
        assert await session.get(FlowLiveTranscripts, loaded.transcript) is None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowRuntimeUploadedFiles)
                .where(FlowRuntimeUploadedFiles.file_id == loaded.files["upload"])
            )
            == 0
        )
    receipt = await _receipt_of(loaded.run_id)
    assert receipt.phase == ReceiptPhase.COMPLETED.value
    assert (receipt.entity_kind, receipt.category, receipt.trigger) == (
        "flow_run",
        "run_record",
        "scheduled",
    )
    assert (receipt.policy_source, receipt.policy_scope_id) == ("flow", flow_id)
    assert (receipt.policy_mode, receipt.policy_days) == ("auto_delete", 1)
    assert receipt.files_deleted == 3 and receipt.rows_deleted > 0
    async with _committed() as session:
        items = set(
            await session.scalars(
                sa.select(RetentionReceiptItems.file_id).where(
                    RetentionReceiptItems.receipt_id == receipt.id
                )
            )
        )
        assert items == set(loaded.files.values())
        audit = await session.scalar(
            sa.select(AuditLogTable).where(
                AuditLogTable.action == ActionType.GALLRING_APPLIED.value,
                AuditLogTable.log_metadata["task"].astext == FLOWS_HISTORY_TASK,
            )
        )
        assert audit is not None
        assert str(receipt.id) in audit.log_metadata["receipt_ids"]
    assert report.counts["runs.runs_deleted"] == 1
    async with _committed() as session:
        snapshot = await session.get(RetentionJobRuns, report.job_run_id)
        assert snapshot is not None and snapshot.overdue_observed_at is not None
        assert (snapshot.overdue_count, snapshot.overdue_complete) == (0, True)


async def test_an_audit_failure_rolls_back_the_deletion_and_its_progress(
    scope, monkeypatch
):
    """Mutant deletion_commits_early."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id)

    async def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(AuditService, "log", failing)
    report = await _history()

    assert report.outcome == RetentionJobOutcome.FAILED
    assert await _run_exists(loaded.run_id) and await _fence(loaded.run_id) is None
    assert await _files_exist(*loaded.files.values()) == set(loaded.files.values())
    async with _committed() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionReceipts)
                .where(RetentionReceipts.entity_id == loaded.run_id)
            )
            == 0
        )


async def test_a_long_run_spans_executions_and_reads_as_deleted_from_the_first(
    scope,
):
    """Mutant no_fence_at_admission."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(
        tenant_id, user_id, flow_id, attempts=30, idempotency_key="long-run"
    )

    first = await _history(chunk_rows=10, budget_rows=40)

    assert first.outcome == RetentionJobOutcome.PARTIAL
    assert await _run_exists(loaded.run_id)
    assert await _fence(loaded.run_id) is not None
    async with _committed() as session:
        runs = FlowRunRepository(session)
        with pytest.raises(FlowRunNotFoundError):
            await runs.get(run_id=loaded.run_id, tenant_id=tenant_id)
        with pytest.raises(FlowRunNotFoundError):
            await runs.get_status(run_id=loaded.run_id, tenant_id=tenant_id)
        assert loaded.run_id not in {
            run.id for run in await runs.list_statuses(tenant_id=tenant_id)
        }
    assert (await _receipt_of(loaded.run_id)).phase != ReceiptPhase.COMPLETED.value

    for _ in range(10):
        report = await _history(chunk_rows=10, budget_rows=40)
        if not await _run_exists(loaded.run_id):
            break
    assert not await _run_exists(loaded.run_id), report
    assert (await _receipt_of(loaded.run_id)).phase == ReceiptPhase.COMPLETED.value


# Stops -------------------------------------------------------------------------


async def test_a_hold_pauses_a_fenced_run_until_it_is_released(scope):
    """Mutants hold_ignored_when_fenced, paused_receipt_pins_admission_cursor."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id, attempts=30)
    await _history(chunk_rows=10, budget_rows=40)
    assert await _fence(loaded.run_id) is not None
    async with _committed() as session:
        await _place_hold(session, tenant_id, flow_id, run_id=loaded.run_id)

    held = await _history()

    assert await _run_exists(loaded.run_id)
    receipt = await _receipt_of(loaded.run_id)
    assert (receipt.phase, receipt.reason) == ("paused", "legal_hold")
    assert held.blocked.get("receipts.legal_hold") == 1
    # A paused deletion must not pin admission beyond the last Flow forever.
    newly_due = await _bare_run(tenant_id, user_id, flow_id)
    for _ in range(2):
        await _history()
    assert not await _run_exists(newly_due)
    assert await _run_exists(loaded.run_id)
    async with _committed() as session:
        await session.execute(
            sa.update(FlowRetentionHolds)
            .where(FlowRetentionHolds.flow_run_id == loaded.run_id)
            .values(
                released_at=sa.func.now(),
                released_by_actor={"type": "system"},
                release_reason="Request answered",
            )
        )

    await _history()

    assert not await _run_exists(loaded.run_id)
    assert (await _receipt_of(loaded.run_id)).phase == ReceiptPhase.COMPLETED.value


async def test_a_lengthened_policy_keeps_unfenced_runs_but_not_a_fenced_one(scope):
    """Mutant fenced_run_follows_policy: once fenced, only a hold stops it."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id, attempts=30)
    await _history(chunk_rows=10, budget_rows=40)
    assert await _fence(loaded.run_id) is not None
    unfenced = await _bare_run(tenant_id, user_id, flow_id)
    await _auto_delete(flow_id, days=30)

    for _ in range(10):
        await _history(chunk_rows=10, budget_rows=40)
        if not await _run_exists(loaded.run_id):
            break

    assert not await _run_exists(loaded.run_id)
    assert await _run_exists(unfenced) and await _fence(unfenced) is None


@pytest.mark.parametrize(
    "nested_link, traversal_limit, root_linked",
    [(False, None, True), (True, None, True), (True, 1, True), (True, None, False)],
    ids=["root_only", "linked_child", "over_depth", "unlinked_parent"],
)
async def test_shared_families_are_kept_or_paused_before_run_deletion(
    scope,
    admin_user,
    flow_retention_assistant_id,
    nested_link,
    traversal_limit,
    root_linked,
    monkeypatch,
):
    """Mutants M108 descendant_first, M110 truncated_ancestor, shared_family_deleted."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id)
    if traversal_limit is not None:
        from eneo.database.tables.files_table import Files
        from eneo.flows.infrastructure import flow_file_family_repo

        monkeypatch.setattr(flow_file_family_repo, "_MAX_FAMILY_DEPTH", traversal_limit)
        middle, _ = await _file(
            tenant_id, user_id, parent_file_id=loaded.files["generated"]
        )
        async with _committed() as session:
            await session.execute(
                sa.update(Files)
                .where(Files.id == loaded.files["derived"])
                .values(parent_file_id=middle)
            )
    if nested_link:
        async with _committed() as session:
            original = await session.scalar(
                sa.select(FlowRunStepResultFiles).where(
                    FlowRunStepResultFiles.flow_run_id == loaded.run_id
                )
            )
            assert original is not None
            if traversal_limit is not None or not root_linked:
                original.file_id = loaded.files["derived"]
                await session.flush()
            values = {
                column.name: getattr(original, column.name)
                for column in FlowRunStepResultFiles.__table__.columns
                if column.name not in {"id", "created_at", "updated_at"}
            }
            if root_linked:
                session.add(
                    FlowRunStepResultFiles(
                        **{
                            **values,
                            "file_id": loaded.files[
                                "generated"
                                if traversal_limit is not None
                                else "derived"
                            ],
                            "ordinal": 1,
                        }
                    )
                )
    async with _committed() as session:
        session.add(
            AssistantsFiles(
                assistant_id=flow_retention_assistant_id,
                file_id=loaded.files["generated"],
            )
        )

    await _history()

    if traversal_limit is not None:
        assert await _run_exists(loaded.run_id)
        receipt = await _receipt_of(loaded.run_id)
        assert receipt.reason == "family_depth_exceeded"
        assert await _files_exist(*loaded.files.values()) == set(loaded.files.values())
        async with _committed() as session:
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RetentionReceiptItems)
                    .where(RetentionReceiptItems.receipt_id == receipt.id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(FlowRunStepResultFiles)
                    .where(FlowRunStepResultFiles.flow_run_id == loaded.run_id)
                )
                == 2
            )
        return
    assert not await _run_exists(loaded.run_id)
    assert await _files_exist(*loaded.files.values()) == {
        loaded.files["generated"],
        loaded.files["derived"],
    }
    receipt = await _receipt_of(loaded.run_id)
    assert receipt.phase == ReceiptPhase.COMPLETED.value
    async with _committed() as session:
        recorded = set(
            await session.scalars(
                sa.select(RetentionReceiptItems.file_id).where(
                    RetentionReceiptItems.receipt_id == receipt.id
                )
            )
        )
    assert loaded.files["generated" if root_linked else "derived"] in recorded


@pytest.mark.parametrize("links, cap", [(1, 3), (20, 22)])
async def test_a_family_over_the_cap_pauses_the_run_until_the_cap_is_raised(
    scope, links, cap
):
    """Mutants M106 own_links_uncharged, family_cap_ignored, manifest_before_fit."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id, attempts=links)
    async with _committed() as session:
        for table in (FlowRunStepInputFiles, FlowRunStepResultFiles):
            original = await session.scalar(
                sa.select(table).where(table.flow_run_id == loaded.run_id)
            )
            assert original is not None
            for attempt in range(2, links + 1):
                values = {
                    column.name: getattr(original, column.name)
                    for column in table.__table__.columns
                    if column.name not in {"id", "created_at", "updated_at"}
                }
                session.add(table(**{**values, "attempt_no": attempt}))
    reports = [await _history(family_rows=cap), await _history(family_rows=cap)]

    assert await _run_exists(loaded.run_id)
    receipt = await _receipt_of(loaded.run_id)
    assert (receipt.phase, receipt.reason) == ("paused", "family_exceeds_budget")
    assert (
        sum(
            report.blocked.get(f"{step}.family_exceeds_budget", 0)
            for report in reports
            for step in ("runs", "receipts")
        )
        == 1
    )
    async with _committed() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionReceiptItems)
                .where(RetentionReceiptItems.receipt_id == receipt.id)
            )
            == 0
        )
        for table in (FlowRunStepInputFiles, FlowRunStepResultFiles):
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(table)
                    .where(table.flow_run_id == loaded.run_id)
                )
                == links
            )
    async with _committed() as session:
        unfinished = await FlowRunHistoryDueRepository(session).receipts()
    assert unfinished.unfinished == 1  # what the status route shows

    await _history()

    assert not await _run_exists(loaded.run_id)
    assert (await _receipt_of(loaded.run_id)).phase == ReceiptPhase.COMPLETED.value


# Bounded examination ---------------------------------------------------------------


async def test_a_blocked_prefix_never_starves_later_runs_and_the_pass_resets(
    test_tenant, admin_user
):
    """Mutants examination_uncharged, cursor_not_durable."""
    tenant_id, user_id = test_tenant.id, admin_user.id
    space_id = await _space(tenant_id, user_id)
    blocked_flow = UUID("00000000-0000-0000-0000-00000000000a")
    open_flow = UUID("ffffffff-0000-0000-0000-00000000000b")
    async with _committed() as session:
        for flow_id in (blocked_flow, open_flow):
            session.add(
                Flows(
                    id=flow_id,
                    name=f"Prefix {flow_id}",
                    tenant_id=tenant_id,
                    space_id=space_id,
                    flow_run_history_retention_mode="auto_delete",
                    flow_run_history_retention_days=1,
                )
            )
    prefix = 25
    for index in range(prefix):
        run_id = await _bare_run(
            tenant_id, user_id, blocked_flow, at=OLD - timedelta(minutes=index)
        )
        async with _committed() as session:
            session.add(
                FlowRunAuditOutbox(
                    tenant_id=tenant_id,
                    flow_id=blocked_flow,
                    flow_run_id=run_id,
                    run_revision=1,
                    description="flow_run_completed:executor_completed",
                    action="flow_run_completed",
                    entity_type="flow_run",
                    entity_id=run_id,
                    actor_id=user_id,
                    actor_type="user",
                    source="executor_completed",
                    target_status="completed",
                    delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                )
            )
    eligible = await _bare_run(tenant_id, user_id, open_flow)
    budget = 10

    # One execution examines at most its budget: it cannot pass the whole prefix.
    first = await _history(chunk_rows=budget, budget_rows=budget)
    assert await _run_exists(eligible)
    assert first.blocked.get("runs.undelivered_audit", 0) < prefix
    executions = 1
    while await _run_exists(eligible):
        executions += 1
        assert executions <= -(-(2 * prefix + 16) // budget) + 2
        await _history(chunk_rows=budget, budget_rows=budget)

    # The next execution passes the whole blocked prefix and ends its pass: the
    # durable cursor is dropped, so the one after starts from the first Flow.
    final = await _history()
    assert final.outcome == RetentionJobOutcome.SUCCEEDED
    assert final.blocked.get("runs.undelivered_audit") == prefix
    async with _committed() as session:
        cursors = await session.scalar(
            sa.select(RetentionJobRuns.cursors).where(
                RetentionJobRuns.id == final.job_run_id
            )
        )
    assert "runs" not in cursors


# Races ---------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["fresh_anchor", "already_admitted"])
async def test_admission_rechecks_the_locked_candidate(scope, change):
    """Mutants M104 stale_due_anchor, M105 readmits_fenced_run."""
    tenant_id, user_id, _, flow_id = scope
    run_id = await _bare_run(tenant_id, user_id, flow_id)
    async with _committed() as session:
        deletion = FlowRunHistoryDeletion(session)
        await deletion.lock()
        now = datetime.now(timezone.utc)
        rules = await deletion.rules.rules(
            modes=SCHEDULED_MODES, after=None, limit=1, flow_id=flow_id
        )
        rule = rules[0] if rules else None
        assert rule is not None
        [due] = await deletion.candidates(rule, now=now, after=None, limit=1)
        if change == "fresh_anchor":
            await session.execute(
                sa.update(FlowRuns).where(FlowRuns.id == run_id).values(finished_at=now)
            )
        else:
            await delete_run(session, run_id, max_rows=6)
        out = RetentionEffects()
        progress = await deletion.admit(
            rule,
            due,
            trigger=RetentionTrigger.SCHEDULED,
            triggered_by_user_id=None,
            out=out,
            rows=100,
            now=now,
        )
        assert progress.receipt is None
        assert (
            out.blocked["not_due" if change == "fresh_anchor" else "already_admitted"]
            == 1
        )
    assert await _run_exists(run_id)


# Explicit purge -------------------------------------------------------------------


async def test_the_explicit_purge_hands_an_unfinished_run_to_the_nightly_task(scope):
    """Mutant pending_not_reported."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id, attempts=30)

    async with _committed() as session:
        result = await purge(
            session,
            tenant_id,
            user_id=user_id,
            max_rows=20,
            max_files=100,
        )

    assert result.candidate_count == 1
    assert result.purged_run_ids == ()
    [pending] = result.pending_receipt_ids
    receipt = await _receipt_of(loaded.run_id)
    assert receipt.id == pending
    assert (receipt.trigger, receipt.triggered_by_user_id) == ("explicit", user_id)
    assert await _fence(loaded.run_id) == pending

    await _history()

    assert not await _run_exists(loaded.run_id)
    finished = await _receipt_of(loaded.run_id)
    assert finished.phase == ReceiptPhase.COMPLETED.value
    assert finished.triggered_by_user_id == user_id


async def test_the_explicit_purge_admits_auto_delete_and_preserve_but_not_review(
    test_tenant, admin_user
):
    """Mutant explicit_admits_review."""
    tenant_id, user_id = test_tenant.id, admin_user.id
    space_id = await _space(tenant_id, user_id)
    runs: dict[str, UUID] = {}
    for mode in ("auto_delete", "preserve", "review_required"):
        flow_id = await _flow(tenant_id, user_id, space_id)
        await _auto_delete(flow_id, mode=mode)
        runs[mode] = await _bare_run(tenant_id, user_id, flow_id)

    async with _committed() as session:
        result = await purge(session, tenant_id, space_id=space_id)

    assert set(result.purged_run_ids) == {runs["auto_delete"], runs["preserve"]}
    assert await _run_exists(runs["review_required"])


@pytest.mark.parametrize("diagnostic", [True, False], ids=["diagnostics", "deletion"])
async def test_explicit_statement_timeout_rolls_back_its_unit(
    scope, monkeypatch, diagnostic
):
    """Mutants explicit_timeout_removed, explicit_timeout_savepoint_removed."""
    tenant_id, user_id, _, flow_id = scope
    run_id = await _bare_run(tenant_id, user_id, flow_id)
    monkeypatch.setattr(get_settings(), "gallring_chunk_statement_timeout_ms", 500)
    repository = (
        FlowRunHistoryDueRepository if diagnostic else FlowRunDeletionRepository
    )
    method = "diagnostics" if diagnostic else "delete_children"
    original = getattr(repository, method)

    async def slow(self, *args, **kwargs):
        await self.session.execute(sa.select(sa.func.pg_sleep(1)))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(repository, method, slow)
    async with _committed() as session:
        explicit = FlowRunHistoryExplicitPurge(session)
        with pytest.raises(DBAPIError):
            if diagnostic:
                await explicit.blocked(
                    PurgeScope(tenant_id=tenant_id), now=datetime.now(timezone.utc)
                )
            else:
                await explicit.run(
                    PurgeScope(tenant_id=tenant_id),
                    now=datetime.now(timezone.utc),
                    limit=10,
                    dry_run=False,
                    triggered_by_user_id=user_id,
                    max_rows=50_000,
                    max_files=10_000,
                )
        assert (
            await session.scalar(sa.select(FlowRuns.id).where(FlowRuns.id == run_id))
            == run_id
        )
        assert (
            await session.scalar(
                sa.select(FlowRuns.retention_receipt_id).where(FlowRuns.id == run_id)
            )
            is None
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(RetentionReceipts)
            )
            == 0
        )


async def test_explicit_guard_obeys_the_configured_lock_limit(scope, monkeypatch):
    """Mutants explicit_guard_removed, retention_lock_fixed_timeout."""
    tenant_id, user_id, _, flow_id = scope
    run_id = await _bare_run(tenant_id, user_id, flow_id)
    monkeypatch.setattr(get_settings(), "gallring_chunk_lock_timeout_ms", 200)
    monkeypatch.setattr(get_settings(), "gallring_chunk_statement_timeout_ms", 2000)
    async with _committed() as holder:
        await acquire_exclusive(holder, RetentionSubject.FLOW_HISTORY)
        async with _committed() as session:
            explicit = FlowRunHistoryExplicitPurge(session)
            with pytest.raises(RetentionLockBusy):
                await asyncio.wait_for(
                    explicit.run(
                        PurgeScope(tenant_id=tenant_id),
                        now=datetime.now(timezone.utc),
                        limit=10,
                        dry_run=False,
                        triggered_by_user_id=user_id,
                        max_rows=50_000,
                        max_files=10_000,
                    ),
                    timeout=1,
                )
            assert (
                await session.scalar(
                    sa.select(FlowRuns.id).where(FlowRuns.id == run_id)
                )
                == run_id
            )
            assert (
                await session.scalar(
                    sa.select(FlowRuns.retention_receipt_id).where(
                        FlowRuns.id == run_id
                    )
                )
                is None
            )


@pytest.fixture
async def flow_retention_assistant_id(scope, completion_model_factory) -> UUID:
    from eneo.database.tables.assistant_table import Assistants

    tenant_id, user_id, space_id, _ = scope
    async with _committed() as session:
        model = await completion_model_factory(session, "gpt-4")
        assistant = Assistants(
            name="History assistant",
            description=None,
            user_id=user_id,
            space_id=space_id,
            completion_model_id=model.id,
            completion_model_kwargs={},
            logging_enabled=False,
            is_default=False,
            published=False,
            data_retention_days=None,
        )
        session.add(assistant)
        await session.flush()
        return assistant.id


async def test_nightly_admission_continues_after_a_partial_chunk(scope):
    """Mutant M135 partial_admission_ends_execution wastes the remaining budget."""
    tenant_id, user_id, _, flow_id = scope
    loaded = [await _loaded_run(tenant_id, user_id, flow_id) for _ in range(20)]

    report = await _history(chunk_rows=100, budget_rows=10_000)

    assert report.counts.get("runs.runs_admitted") == len(loaded)
    assert report.counts.get("runs.runs_deleted", 0) >= 10
    for run in loaded:
        assert not await _run_exists(run.run_id) or await _fence(run.run_id) is not None


async def test_purge_diagnostics_use_a_global_window_and_two_queries(scope):
    """Mutant M136 per_flow_diagnostics causes unbounded request query fan-out."""
    from sqlalchemy import event

    tenant_id, user_id, space_id, _ = scope
    for _ in range(4):
        flow_id = await _flow(tenant_id, user_id, space_id)
        await _auto_delete(flow_id)
        await _bare_run(tenant_id, user_id, flow_id)
    statements: list[str] = []
    async with _committed() as session:
        engine = session.bind
        assert engine is not None

        def record_query(
            connection, cursor, statement, parameters, context, executemany
        ):
            if (
                statement.lstrip().upper().startswith("SELECT")
                and "flow_runs" in statement
            ):
                statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_query)
        try:
            result = await FlowRunHistoryExplicitPurge(session).blocked(
                PurgeScope(tenant_id), now=datetime.now(timezone.utc)
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record_query)
    assert (result.counted_runs, result.legal_hold, result.complete) == (4, 0, True)
    assert len(statements) == 2


@pytest.mark.parametrize(
    "other_run_consumes", [False, True], ids=["unconsumed", "consumed"]
)
async def test_shared_upload_ownership_controls_binding_and_transcript_release(
    scope, flow_retention_assistant_id, other_run_consumes
):
    """Mutants M137 ignore_consumption and M138 keep_unconsumed_binding."""
    tenant_id, user_id, _, flow_id = scope
    loaded = await _loaded_run(tenant_id, user_id, flow_id)
    upload = loaded.files["upload"]
    other_run = (
        await _bare_run(tenant_id, user_id, flow_id) if other_run_consumes else None
    )
    async with _committed() as session:
        session.add(
            AssistantsFiles(assistant_id=flow_retention_assistant_id, file_id=upload)
        )
        if other_run is not None:
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == other_run)
                .values(status="queued")
            )
            session.add(
                FlowRunStepInputFiles(
                    flow_run_id=other_run,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=uuid4(),
                    step_order=1,
                    attempt_no=1,
                    file_id=upload,
                    ordinal=0,
                )
            )

    await _history()

    assert not await _run_exists(loaded.run_id)
    assert await _files_exist(upload) == {upload}
    async with _committed() as session:
        bound = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuntimeUploadedFiles)
            .where(FlowRuntimeUploadedFiles.file_id == upload)
        )
        transcripts = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowLiveTranscripts)
            .where(FlowLiveTranscripts.id == loaded.transcript)
        )
    assert (bound, transcripts) == ((1, 1) if other_run_consumes else (0, 0))
    if other_run is not None:
        assert await _run_exists(other_run)
