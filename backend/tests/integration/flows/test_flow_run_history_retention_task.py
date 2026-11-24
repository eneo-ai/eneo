"""The five-minute removal of Flow runs after their shared space's time.

A run is taken when it started while its shared space had a time, the space
still has one, and the time (or the flow's shorter time) has passed. It goes
whole, with its files, or not at all; a run it cannot take stays and is
reported.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_readback import (
    RetentionReadback,
    RetentionReadbackFailed,
)
from eneo.data_retention.application.retention_runner import (
    RetentionContractError,
    RetentionRunReport,
)
from eneo.data_retention.domain.retention import (
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure import gallring_lock
from eneo.data_retention.infrastructure.gallring_lock import (
    GallringSubject,
    acquire_exclusive,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowRetentionHolds,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_usage import FileUsageRepository
from eneo.flows.application.flow_run_history_retention_task import (
    FLOW_RUN_HISTORY_TASK,
)
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeRepository,
)
from eneo.main.config import Settings, get_settings
from eneo.main.retention_tasks import retention_task_registrations
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import ContentState
from eneo.object_content.reconciliation import ObjectContentReconciler
from tests.integration.data_retention.retention_support import run_registered_retention
from tests.integration.test_flow_runtime_retention_cleanup import (
    FlowRuntimeRetentionFixture,
    _add_flow_audit_outbox_row,
    _create_durable_file,
    _create_flow_runtime_fixture,
    _set_webhook_delivery_pending,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SPACE_DAYS = 30


@pytest.fixture
async def shared_space(retention_session: AsyncSession, space_factory) -> Spaces:
    return await space_factory(
        retention_session,
        f"Shared retention space {uuid4()}",
        data_retention_days=SPACE_DAYS,
    )


@pytest.fixture
async def space_assistant(
    retention_session: AsyncSession,
    shared_space: Spaces,
    admin_user,
    completion_model_factory,
) -> Assistants:
    model = await completion_model_factory(retention_session, "gpt-4")
    assistant = Assistants(
        name="Flow retention assistant",
        description="Flow run retention",
        user_id=admin_user.id,
        space_id=shared_space.id,
        completion_model_id=model.id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=False,
        data_retention_days=None,
    )
    retention_session.add(assistant)
    await retention_session.flush()
    return assistant


async def _aged_run(
    session: AsyncSession,
    *,
    tenant,
    user,
    space: Spaces,
    assistant: Assistants,
    days_old: int,
    flow_days: int | None = None,
    marked: bool = True,
) -> FlowRuntimeRetentionFixture:
    return await _create_flow_runtime_fixture(
        session,
        tenant=tenant,
        user=user,
        space=space,
        assistant=assistant,
        days_old=days_old,
        flow_retention_days=flow_days,
        marked=marked,
    )


async def _small_run(
    session: AsyncSession,
    fixture: FlowRuntimeRetentionFixture,
    *,
    days_old: int,
    with_step: bool = False,
) -> UUID:
    """A run of the fixture's flow without files: two rows to remove with its
    discovery, or four with a step result and an attempt."""
    at = datetime.now(timezone.utc) - timedelta(days=days_old)
    run = FlowRuns(
        id=uuid4(),
        flow_id=fixture.flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=fixture.run.principal_user_id,
        tenant_id=fixture.run.tenant_id,
        trace_id=uuid4(),
        status="completed",
        started_at=at,
        finished_at=at,
        input_payload_json={},
        output_payload_json={},
        started_under_space_retention=True,
        created_at=at,
        updated_at=at,
    )
    session.add(run)
    await session.flush()
    if with_step:
        common: dict[str, Any] = {
            "flow_run_id": run.id,
            "flow_id": fixture.flow.id,
            "tenant_id": fixture.run.tenant_id,
            "step_id": fixture.step_id,
            "step_order": 1,
            "status": "completed",
            "started_at": at,
            "finished_at": at,
            "created_at": at,
            "updated_at": at,
        }
        session.add(
            FlowStepResults(
                **common,
                assistant_id=fixture.step_result.assistant_id,
                input_payload_json={},
                output_payload_json={},
                model_parameters_json={},
            )
        )
        session.add(FlowStepAttempts(**common, attempt_no=1))
        await session.flush()
    return run.id


async def _run(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    error_code: RetentionErrorCode | None = None,
) -> RetentionRunReport:
    return await run_registered_retention(
        session,
        task_name=FLOW_RUN_HISTORY_TASK,
        now=now or datetime.now(timezone.utc),
        settings=settings,
        error_code=error_code,
    )


async def _has_due(session: AsyncSession, *, now: datetime) -> bool:
    [registration] = [
        task
        for task in retention_task_registrations(get_settings(), now=now)
        if task.name == FLOW_RUN_HISTORY_TASK
    ]
    return await registration.build(session).has_due()


async def _exists(session: AsyncSession, run_id: UUID) -> bool:
    return (
        await session.scalar(select(FlowRuns.id).where(FlowRuns.id == run_id))
        is not None
    )


async def _file_exists(session: AsyncSession, file_id: UUID) -> bool:
    return await session.scalar(select(Files.id).where(Files.id == file_id)) is not None


async def _hold(session: AsyncSession, *, flow_id: UUID, user_id: UUID, tenant_id):
    now = datetime.now(timezone.utc)
    session.add(
        FlowRetentionHolds(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=None,
            reason="Recorded request",
            review_by=now + timedelta(days=30),
            created_by_actor={"type": "user", "id": str(user_id)},
            created_at=now,
        )
    )
    await session.flush()


def _counts(report: RetentionRunReport) -> dict[str, int]:
    return {key: value for key, value in report.counts.items() if value}


def _blocked(report: RetentionRunReport) -> dict[str, int]:
    return {key: value for key, value in report.blocked.items() if value}


class _Database(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


async def test_the_space_time_removes_marked_due_runs_whole(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    """Mutants: the task without the mark; without the flow's shorter time;
    a run counted from another run's time; a run removed without its files."""
    session = retention_session
    args = dict(
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
    )
    due = await _aged_run(session, days_old=SPACE_DAYS + 10, **args)
    young = await _aged_run(session, days_old=SPACE_DAYS - 10, **args)
    flow_shorter = await _aged_run(
        session, days_old=SPACE_DAYS - 10, flow_days=5, **args
    )
    unmarked = await _aged_run(session, days_old=SPACE_DAYS + 10, marked=False, **args)
    session.add(
        FlowLiveTranscripts(
            tenant_id=test_tenant.id,
            user_id=admin_user.id,
            flow_id=due.flow.id,
            flow_version=1,
            step_id=due.step_id,
            model_id=uuid4(),
            recording_id="recording-1",
            text="Hej.",
            segments=None,
            received_audio_seconds=1.0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            bound_file_id=due.runtime_input_file.id,
            bound_file_ids=[due.runtime_input_file.id],
        )
    )
    await session.flush()
    now = datetime.now(timezone.utc)
    assert await _has_due(session, now=now)

    report = await _run(session, now=now)

    assert report.outcome is RetentionJobOutcome.SUCCEEDED, report
    assert not _blocked(report), report
    counts = _counts(report)
    assert counts["runs.runs_deleted"] == 2, counts
    assert counts["runs.uploads_released"] == 2, counts
    assert counts["runs.live_transcripts_deleted"] == 1, counts
    assert counts["runs.roots_deleted"] == 4, counts
    for gone in (due, flow_shorter):
        assert not await _exists(session, gone.run.id)
        assert not await _file_exists(session, gone.generated_file.id)
        assert not await _file_exists(session, gone.runtime_input_file.id)
        for table in (FlowStepResults, FlowRunStepInputFiles, FlowRunStepResultFiles):
            assert not await session.scalar(
                select(func.count())
                .select_from(table)
                .where(table.flow_run_id == gone.run.id)
            )
        assert not await session.scalar(
            select(func.count())
            .select_from(FlowRuntimeUploadedFiles)
            .where(FlowRuntimeUploadedFiles.file_id == gone.runtime_input_file.id)
        )
    assert not await session.scalar(
        select(func.count())
        .select_from(FlowLiveTranscripts)
        .where(FlowLiveTranscripts.flow_id == due.flow.id)
    )
    for kept in (young, unmarked):
        assert await _exists(session, kept.run.id)
        assert await _file_exists(session, kept.runtime_input_file.id)
    assert not await _has_due(session, now=now)


async def test_without_the_space_time_nothing_goes_until_it_is_set_again(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    """Mutant: the selection without the space's time now, so the flow's own
    time removes a marked run after the space's time was removed."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=10,
        flow_days=5,
    )
    run_id = run.run.id
    space_id = shared_space.id
    await session.execute(
        update(Spaces).where(Spaces.id == space_id).values(data_retention_days=None)
    )
    now = datetime.now(timezone.utc)
    assert not await _has_due(session, now=now)

    report = await _run(session, now=now)

    assert not _counts(report), report
    assert await _exists(session, run_id)

    await session.execute(
        update(Spaces)
        .where(Spaces.id == space_id)
        .values(data_retention_days=SPACE_DAYS)
    )
    assert await _has_due(session, now=now)
    report = await _run(session, now=now)

    assert _counts(report)["runs.runs_deleted"] == 1, report
    assert not await _exists(session, run_id)


@pytest.mark.parametrize("blocker", ["hold", "audit", "webhook"])
async def test_a_held_or_undelivered_run_stays_and_the_probe_says_no(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    blocker: str,
):
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    now = datetime.now(timezone.utc)
    if blocker == "hold":
        await _hold(
            session,
            flow_id=run.flow.id,
            user_id=admin_user.id,
            tenant_id=test_tenant.id,
        )
    elif blocker == "audit":
        await _add_flow_audit_outbox_row(
            session,
            run=run.run,
            user_id=admin_user.id,
            delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
            with_audit_log=False,
        )
    else:
        await _set_webhook_delivery_pending(
            session,
            delivery_id=run.webhook_delivery.id,
            now=now,
            claim_expires_at=None,
        )
    run_id = run.run.id
    assert not await _has_due(session, now=now)

    report = await _run(session, now=now)

    assert report.outcome is RetentionJobOutcome.SUCCEEDED, report
    assert not _counts(report) and not _blocked(report), report
    assert await _exists(session, run_id)


@pytest.mark.parametrize(
    ("chunk", "rows", "same_pass"),
    [(20, None, True), (2000, 20, False)],
    ids=["chunk-is-the-room", "execution-is-the-room"],
)
async def test_an_oversized_run_is_blocked_before_its_locks_and_a_smaller_one_goes(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    chunk: int,
    rows: int | None,
    same_pass: bool,
):
    """A run with more rows than one removal can take is blocked by a bounded
    count before anything else of it is read or locked, so a transcript edit
    on it does not hide it as locked. When the pass has fewer rows than the
    chunk, the pass is the run's whole room: blocked, not deferred, and the
    next pass goes on after it. Mutants: an oversized run deferred like one
    that does not fit the rest of the pass, which would end every pass at it;
    the run's rows counted after its locks."""
    session = retention_session
    oversized = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    at = oversized.run.created_at
    session.add_all(
        FlowStepAttempts(
            flow_run_id=oversized.run.id,
            flow_id=oversized.flow.id,
            tenant_id=test_tenant.id,
            step_id=oversized.step_id,
            step_order=1,
            attempt_no=attempt_no,
            status="completed",
            started_at=at,
            finished_at=at,
            created_at=at,
            updated_at=at,
        )
        for attempt_no in range(2, 32)
    )
    small = await _small_run(session, oversized, days_old=SPACE_DAYS + 5)
    oversized_id = oversized.run.id
    step_result_id = oversized.step_result.id
    await session.commit()
    limits: dict[str, object] = {
        "retention_chunk_rows": chunk,
        "retention_max_family_rows": 3,
    }
    if rows is not None:
        limits["retention_max_rows_per_run"] = rows
    settings = get_settings().model_copy(update=limits)

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            select(FlowStepResults.id)
            .where(FlowStepResults.id == step_result_id)
            .with_for_update()
        )
        report = await _run(session, settings=settings)

    assert _blocked(report) == {"runs.unit_exceeds_budget": 1}, report
    assert await _exists(session, oversized_id)
    with pytest.raises(RetentionReadbackFailed, match="unit_exceeds_budget"):
        RetentionReadback([FLOW_RUN_HISTORY_TASK]).add_round([report])
    if not same_pass:
        assert await _exists(session, small)
        report = await _run(session, settings=settings)
    assert _counts(report)["runs.runs_deleted"] == 1, report
    assert not await _exists(session, small)
    assert await _exists(session, oversized_id)


@pytest.mark.parametrize(
    ("chunk", "family", "rows"),
    [(4, 3, 5), (2000, 3, 5)],
    ids=["chunk-is-the-room", "execution-is-the-room"],
)
async def test_a_nearly_spent_pass_defers_a_run_instead_of_blocking_it(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    chunk: int,
    family: int,
    rows: int,
):
    """Mutant: a run that does not fit what is left of the pass reported as
    too large, although a fresh pass removes it."""
    session = retention_session
    first = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS - 10,
    )
    older = await _small_run(session, first, days_old=SPACE_DAYS + 10)
    later = await _small_run(session, first, days_old=SPACE_DAYS + 5, with_step=True)
    settings = get_settings().model_copy(
        update={
            "retention_chunk_rows": chunk,
            "retention_max_family_rows": family,
            "retention_max_rows_per_run": rows,
            "retention_chunk_gather_seconds": 60.0,
        }
    )

    report = await _run(session, settings=settings)

    assert report.outcome is RetentionJobOutcome.PARTIAL, report
    assert not _blocked(report), report
    assert _counts(report)["runs.runs_deleted"] == 1, report
    assert not await _exists(session, older)
    assert await _exists(session, later)

    report = await _run(session, settings=settings)

    assert not _blocked(report), report
    assert not await _exists(session, later)


@pytest.mark.parametrize(
    ("error", "outcome", "error_code"),
    [
        (RuntimeError("boom"), RetentionJobOutcome.SUCCEEDED, None),
        (
            DBAPIError("DELETE", {}, _Database("57014")),
            RetentionJobOutcome.PARTIAL,
            RetentionErrorCode.CHUNK_TIMEOUT,
        ),
        (
            DBAPIError("DELETE", {}, _Database("40P01")),
            RetentionJobOutcome.PARTIAL,
            RetentionErrorCode.CHUNK_DEADLOCK,
        ),
        (
            RetentionContractError("engine"),
            RetentionJobOutcome.FAILED,
            RetentionErrorCode.CONTRACT_VIOLATION,
        ),
    ],
    ids=["defect", "timeout", "deadlock", "contract"],
)
async def test_a_run_that_raises_is_blocked_and_the_others_go(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: RetentionJobOutcome,
    error_code: RetentionErrorCode | None,
):
    """A defect blocks its run as run_failed; a transient database error ends
    the pass as partial; the engine's own errors propagate. Mutants: catching
    the transient error as a defect; catching the contract error."""
    session = retention_session
    failing = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    other = await _small_run(session, failing, days_old=SPACE_DAYS + 5)
    failing_id = failing.run.id
    original = FlowRunHistoryPurgeRepository._remove_run

    async def _remove_run(self, run_id: UUID, *args: Any, **kwargs: Any):
        if run_id == failing_id:
            raise error
        return await original(self, run_id, *args, **kwargs)

    monkeypatch.setattr(FlowRunHistoryPurgeRepository, "_remove_run", _remove_run)

    report = await _run(session, error_code=error_code)

    assert report.outcome is outcome, report
    assert await _exists(session, failing_id)
    if error_code is None:
        assert _blocked(report) == {"runs.run_failed": 1}, report
        assert _counts(report)["runs.runs_deleted"] == 1, report
        assert not await _exists(session, other)
    else:
        assert not _counts(report), report
        assert await _exists(session, other)


@pytest.mark.parametrize("held", ["run", "step_result", "explicit_purge"])
async def test_a_run_another_transaction_holds_stays_as_run_locked(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    held: str,
):
    """A writer on the run, a transcript edit (it locks the step result first,
    then reaches the run through its foreign key) and the administrator's
    purge each keep the run from this pass, without a wait, and the pass is not
    clean. Mutants: removing a run whose step result is locked; waiting on
    the lock; counting a locked run as removed."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    run_id = run.run.id
    step_result_id = run.step_result.id
    await session.commit()

    async with sessionmanager.session() as holder, holder.begin():
        if held == "run":
            await holder.execute(
                select(FlowRuns.id).where(FlowRuns.id == run_id).with_for_update()
            )
        elif held == "step_result":
            await holder.execute(
                select(FlowStepResults.id)
                .where(FlowStepResults.id == step_result_id)
                .with_for_update()
            )
        else:
            result = await FlowRetentionRepository(
                holder
            ).purge_due_flow_run_history_for_tenant(
                tenant_id=test_tenant.id,
                now=datetime.now(timezone.utc),
                limit=10,
                dry_run=False,
            )
            assert result.purged_run_ids == (run_id,)

        report = await _run(session)

    assert _blocked(report) == {"runs.run_locked": 1}, report
    assert not _counts(report), report
    with pytest.raises(RetentionReadbackFailed, match="run_locked"):
        RetentionReadback([FLOW_RUN_HISTORY_TASK]).add_round([report])
    if held == "explicit_purge":
        assert not await _exists(session, run_id)
        return
    assert await _exists(session, run_id)
    assert await _file_exists(session, run.runtime_input_file.id)

    report = await _run(session)

    assert _counts(report)["runs.runs_deleted"] == 1, report
    assert not await _exists(session, run_id)


async def test_a_pdf_run_goes_whole_and_its_content_is_tombstoned(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    """A PDF input with an extracted image: while another transaction holds
    the image, the run stays whole (run, binding and files); the next pass
    removes it, and reconciliation leaves its content unreadable. A file a
    remaining run uses stays. Mutant: the run deleted before its files were
    released, so a locked child left a run gone and its file readable."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    source_id = run.runtime_input_file.id
    run.runtime_input_file.mimetype = "application/pdf"
    child = await _create_durable_file(
        session,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        name="page-1.png",
        mimetype="image/png",
        file_type=FileType.IMAGE,
        payload=b"p" * 13,
        variant=FileContentVariant.ORIGINAL,
        created_at=datetime.now(timezone.utc),
        parent_file_id=source_id,
    )
    child_id = child.id
    remaining = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=1,
    )
    shared_result = await _create_durable_file(
        session,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        name="shared.docx",
        mimetype="text/plain",
        file_type=FileType.TEXT,
        payload=b"s" * 7,
        variant=FileContentVariant.GENERATED_ARTIFACT,
        created_at=datetime.now(timezone.utc),
    )
    for owner, ordinal in ((run, 1), (remaining, 1)):
        session.add(
            FlowRunStepResultFiles(
                flow_run_id=owner.run.id,
                flow_id=owner.flow.id,
                tenant_id=test_tenant.id,
                step_result_id=owner.step_result.id,
                step_id=owner.step_id,
                step_order=1,
                attempt_no=1,
                file_id=shared_result.id,
                ordinal=ordinal,
                source="declared_artifact",
            )
        )
    await session.flush()
    removed_files = (source_id, child_id, run.generated_file.id)
    content_ids = set(
        await session.scalars(
            select(FileContentReferences.content_id).where(
                FileContentReferences.file_id.in_(removed_files)
            )
        )
    )
    assert len(content_ids) == 3
    run_id = run.run.id
    shared_id = shared_result.id
    await session.commit()

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            select(Files.id).where(Files.id == child_id).with_for_update()
        )
        report = await _run(session)

    assert _blocked(report) == {"runs.run_locked": 1}, report
    assert not _counts(report), report
    assert await _exists(session, run_id)
    for file_id in removed_files:
        assert await _file_exists(session, file_id)
    assert await session.scalar(
        select(func.count())
        .select_from(FlowRuntimeUploadedFiles)
        .where(FlowRuntimeUploadedFiles.file_id == source_id)
    )

    report = await _run(session)

    assert not _blocked(report), report
    counts = _counts(report)
    assert counts["runs.runs_deleted"] == 1, counts
    assert counts["runs.files_in_use"] == 1, counts
    assert not await _exists(session, run_id)
    for file_id in removed_files:
        assert not await _file_exists(session, file_id)
    assert await _file_exists(session, shared_id)
    assert await _exists(session, remaining.run.id)
    await session.commit()

    await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None), sessionmanager
    ).run_once()

    async with session.begin():
        states = set(
            await session.scalars(
                select(ObjectContents.state).where(ObjectContents.id.in_(content_ids))
            )
        )
    assert states == {ContentState.TOMBSTONED.value}


async def test_a_run_kept_after_a_released_file_still_charges_that_file(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    """The run's result file is released, then another transaction holds an
    image extracted from its input: the run rolls back whole, and the released
    family still counts against the pass's files, so a later run that needs
    two files waits for the next pass. Mutant: a rolled-back run charged no
    files, which let one pass use more files than its budget."""
    session = retention_session
    kept = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    kept.runtime_input_file.mimetype = "application/pdf"
    image = await _create_durable_file(
        session,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        name="page-1.png",
        mimetype="image/png",
        file_type=FileType.IMAGE,
        payload=b"p" * 13,
        variant=FileContentVariant.ORIGINAL,
        created_at=datetime.now(timezone.utc),
        parent_file_id=kept.runtime_input_file.id,
    )
    later = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 5,
    )
    kept_id, image_id, later_id = kept.run.id, image.id, later.run.id
    kept_result_id = kept.generated_file.id
    await session.commit()
    settings = get_settings().model_copy(
        update={"retention_max_files_per_run": 2, "retention_max_family_rows": 3}
    )

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            select(Files.id).where(Files.id == image_id).with_for_update()
        )
        report = await _run(session, settings=settings)

    assert _blocked(report) == {"runs.run_locked": 1}, report
    assert await _exists(session, kept_id)
    assert await _file_exists(session, kept_result_id)
    assert await _exists(session, later_id)

    report = await _run(session, settings=settings)

    assert _counts(report)["runs.runs_deleted"] == 1, report
    assert not await _exists(session, later_id)


async def test_an_error_after_the_first_released_file_rolls_back_the_whole_run(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutant: the run removed outside its savepoint, so a failed second file
    left the run and its first file gone."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    original = FileUsageRepository.delete_unused_root
    calls = 0

    async def delete_unused_root(self, file_id: UUID, **kwargs: int):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("the second file failed")
        return await original(self, file_id, **kwargs)

    monkeypatch.setattr(FileUsageRepository, "delete_unused_root", delete_unused_root)

    report = await _run(session)

    assert calls == 2
    assert _blocked(report) == {"runs.run_failed": 1}, report
    assert not _counts(report), report
    assert await _exists(session, run.run.id)
    for file_id in (run.generated_file.id, run.runtime_input_file.id):
        assert await _file_exists(session, file_id)


async def test_a_hold_placed_after_the_selection_keeps_the_run(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutant: the removal without the recheck under the run's lock."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    run_id = run.run.id
    flow_id = run.flow.id
    original = FlowRetentionRepository.next_run_due_for_removal

    async def next_run_due_for_removal(self, **kwargs: Any):
        found = await original(self, **kwargs)
        if found is not None:
            async with sessionmanager.session() as other, other.begin():
                await _hold(
                    other,
                    flow_id=flow_id,
                    user_id=admin_user.id,
                    tenant_id=test_tenant.id,
                )
        return found

    monkeypatch.setattr(
        FlowRetentionRepository, "next_run_due_for_removal", next_run_due_for_removal
    )

    report = await _run(session)

    assert _counts(report) == {"runs.not_purgeable": 1}, report
    assert not _blocked(report), report
    assert await _exists(session, run_id)


async def _wait_for_a_lock_wait() -> None:
    async with sessionmanager.session() as probe:
        for _ in range(200):
            async with probe.begin():
                waiting = await probe.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks"
                        " WHERE locktype = 'advisory' AND NOT granted"
                    )
                )
            if waiting:
                return
            await asyncio.sleep(0.02)
    raise AssertionError("The pass never waited on the gallring lock.")


@pytest.mark.parametrize("change", ["removed", "extended"])
async def test_a_time_changed_while_the_pass_waits_keeps_the_run(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    change: str,
):
    """Mutant: the selection read before the gallring lock, so the pass
    removed a run by a time already changed."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    run_id = run.run.id
    space_id = shared_space.id
    await session.commit()

    async with sessionmanager.session() as holder:
        await holder.begin()
        await acquire_exclusive(holder, GallringSubject.FLOW_HISTORY)
        await holder.execute(
            update(Spaces)
            .where(Spaces.id == space_id)
            .values(data_retention_days=None if change == "removed" else 365)
        )
        pending = asyncio.create_task(_run(session))
        await _wait_for_a_lock_wait()
        await holder.commit()
        report = await pending

    assert not _counts(report) and not _blocked(report), report
    assert await _exists(session, run_id)


async def test_a_busy_gallring_lock_ends_the_pass_as_partial(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    monkeypatch: pytest.MonkeyPatch,
):
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    run_id = run.run.id
    await session.commit()
    monkeypatch.setattr(gallring_lock, "GALLRING_LOCK_TIMEOUT", "100ms")

    async with sessionmanager.session() as holder, holder.begin():
        await acquire_exclusive(holder, GallringSubject.FLOW_HISTORY)
        report = await _run(session, error_code=RetentionErrorCode.CHUNK_TIMEOUT)

    assert report.outcome is RetentionJobOutcome.PARTIAL, report
    assert await _exists(session, run_id)


async def test_the_probe_follows_the_selection_an_hour_back(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    """The health read builds the task an hour back: a run due for half an
    hour is not overdue yet."""
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS,
    )
    finished = datetime.now(timezone.utc) - timedelta(days=SPACE_DAYS, minutes=30)
    await session.execute(
        update(FlowRuns)
        .where(FlowRuns.id == run.run.id)
        .values(finished_at=finished, created_at=finished)
    )
    now = datetime.now(timezone.utc)

    assert await _has_due(session, now=now)
    assert not await _has_due(session, now=now - timedelta(hours=1))


@pytest.mark.parametrize(
    ("case", "automatic", "explicit"),
    [
        ("on", True, True),
        ("flow_time_only", False, True),
        ("personal_space", False, True),
        ("hold", False, False),
        ("audit", False, False),
        ("webhook", False, False),
        ("off", False, True),
        ("on_again", True, True),
    ],
)
async def test_the_automatic_selection_the_probe_and_the_explicit_purge_agree(
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
    case: str,
    automatic: bool,
    explicit: bool,
):
    """At one time, the automatic selection and its probe agree, and differ
    from the administrator's preview and purge only by the mark and the
    space's time now."""
    session = retention_session
    space = shared_space
    if case == "personal_space":
        space = Spaces(
            name=f"Personal {uuid4()}",
            tenant_id=test_tenant.id,
            user_id=admin_user.id,
            tenant_space_id=None,
            data_retention_days=SPACE_DAYS,
        )
        session.add(space)
        await session.flush()
    # Marked also in the personal space: the selection, not only the mark,
    # leaves a personal space's runs.
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
        flow_days=5,
        marked=case != "flow_time_only",
    )
    now = datetime.now(timezone.utc)
    if case == "flow_time_only":
        space.data_retention_days = None
    elif case == "hold":
        await _hold(
            session,
            flow_id=run.flow.id,
            user_id=admin_user.id,
            tenant_id=test_tenant.id,
        )
    elif case == "audit":
        await _add_flow_audit_outbox_row(
            session,
            run=run.run,
            user_id=admin_user.id,
            delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
            with_audit_log=False,
        )
    elif case == "webhook":
        await _set_webhook_delivery_pending(
            session, delivery_id=run.webhook_delivery.id, now=now, claim_expires_at=None
        )
    elif case in {"off", "on_again"}:
        space.data_retention_days = None
        if case == "on_again":
            await session.flush()
            space.data_retention_days = SPACE_DAYS
    await session.flush()
    repo = FlowRetentionRepository(session)

    selected = await repo.next_run_due_for_removal(now=now, after=None)
    preview = await repo.purge_due_flow_run_history_for_tenant(
        tenant_id=test_tenant.id, now=now, limit=10, dry_run=True
    )

    assert (selected is not None and selected[1] == run.run.id) is automatic
    assert await repo.has_run_due_for_removal(now=now) is automatic
    assert await _has_due(session, now=now) is automatic
    assert (preview.candidate_count == 1) is explicit
    purged = await repo.purge_due_flow_run_history_for_tenant(
        tenant_id=test_tenant.id, now=now, limit=10, dry_run=False
    )
    assert (purged.purged_run_ids == (run.run.id,)) is explicit


async def test_a_link_signed_before_the_removal_finds_nothing(
    client,
    admin_user_api_key,
    retention_session: AsyncSession,
    test_tenant,
    admin_user,
    shared_space: Spaces,
    space_assistant: Assistants,
):
    session = retention_session
    run = await _aged_run(
        session,
        tenant=test_tenant,
        user=admin_user,
        space=shared_space,
        assistant=space_assistant,
        days_old=SPACE_DAYS + 10,
    )
    file_id = run.generated_file.id
    await session.commit()
    signed = await client.post(
        f"/api/v1/files/{file_id}/signed-url/",
        json={"content_disposition": "attachment"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert signed.status_code == 200, signed.text

    report = await _run(session)

    assert _counts(report)["runs.runs_deleted"] == 1, report
    url = urlsplit(signed.json()["url"])
    download = await client.get(f"{url.path}?{url.query}")
    assert download.status_code == 404, download.text
