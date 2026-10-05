"""The gallring runner against real PostgreSQL, driven by a minimal fake task.

The fake task deletes its own work items (receipts of task `tests.fake`), so the
claim, ownership fence, budget, timeout, required audit and skip rules are
observed on committed rows without any flows code.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.application.retention_receipts import (
    PHYSICAL_CONFIRMATION_BLOCKED_KEYS,
    PHYSICAL_CONFIRMATION_COUNT_KEYS,
    RECEIPT_PRUNING_COUNT_KEYS,
    RetentionReceiptService,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionChunkLimits,
    RetentionContractError,
    RetentionRunner,
    RetentionRunReport,
    RetentionStep,
    RetentionStepResult,
    RetentionTenantEffect,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import (
    ManifestPosition,
    NewRetentionReceipt,
    PrunedReceipts,
    RetentionBudget,
    RetentionCategory,
    RetentionEntityKind,
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
    retention_batch_audit_id,
)
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.data_retention.infrastructure.retention_receipt_repo import (
    RetentionReceiptRepository,
)
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.retention_tables import (
    RetentionJobRuns,
    RetentionReceiptItems,
    RetentionReceipts,
)
from eneo.files.file_models import FileContentVariant, FileType
from eneo.object_content.content import ContentAccessClass, ContentState, StorageKind

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_TASK = "tests.fake"
_NOW = datetime.now(timezone.utc)


@asynccontextmanager
async def _committed() -> AsyncIterator[AsyncSession]:
    async with sessionmanager.session() as session, session.begin():
        yield session


class _FakeTask:
    """Deletes up to `batch.rows` of its work items per step call.

    Work items are the fake task's own completed receipts in the
    abandoned_upload category; `extra_steps` run after the deleting step.
    """

    count_keys = frozenset({"deleted", "confirmed"})
    blocked_keys = frozenset({"busy"})

    def __init__(
        self,
        session: AsyncSession,
        after_batch: Callable[[RetentionBatch], Awaitable[None]] | None = None,
        extra_steps: tuple[RetentionStep, ...] = (),
        counts: Callable[[int], Mapping[str, int]] = lambda n: {"deleted": n},
    ) -> None:
        self.session = session
        self.after_batch = after_batch
        self.extra_steps = extra_steps
        self.counts = counts

    @property
    def name(self) -> str:
        return _TASK

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep(name="items", run=self._items), *self.extra_steps)

    async def _items(self, batch: RetentionBatch) -> RetentionStepResult:
        ids = list(
            await self.session.scalars(
                sa.select(RetentionReceipts.id)
                .where(
                    RetentionReceipts.task == _TASK,
                    RetentionReceipts.category == "abandoned_upload",
                )
                .order_by(RetentionReceipts.id)
                .limit(batch.rows)
                .with_for_update()
            )
        )
        deleted = list(
            (
                await self.session.execute(
                    sa.delete(RetentionReceipts)
                    .where(uuid_in(RetentionReceipts.id, ids))
                    .returning(RetentionReceipts.tenant_id)
                )
            ).scalars()
        )
        per_tenant: dict[UUID, int] = {}
        for tenant_id in deleted:
            per_tenant[tenant_id] = per_tenant.get(tenant_id, 0) + 1
        if self.after_batch is not None:
            await self.after_batch(batch)
        return RetentionStepResult(
            rows=len(ids),
            effects=tuple(
                RetentionTenantEffect(tenant_id=tenant, counts=self.counts(count))
                for tenant, count in per_tenant.items()
            ),
            exhausted=len(ids) < batch.rows,
        )


@dataclass
class _Task:
    """A task made of the given steps and names."""

    steps_: tuple[RetentionStep, ...]
    count_keys: frozenset[str] = frozenset({"deleted"})
    blocked_keys: frozenset[str] = frozenset({"busy"})
    name: str = _TASK

    def steps(self) -> Sequence[RetentionStep]:
        return self.steps_


def _receipt_row(
    tenant_id: UUID,
    *,
    phase: str,
    category: str = "abandoned_upload",
    **values: Any,
) -> RetentionReceipts:
    return RetentionReceipts(
        task=_TASK,
        entity_kind="file_family",
        entity_id=uuid4(),
        category=category,
        trigger="scheduled",
        tenant_id=tenant_id,
        phase=phase,
        started_at=values.pop("started_at", _NOW),
        updated_at=_NOW,
        **values,
    )


async def _work_items(tenant_id: UUID, count: int) -> list[UUID]:
    async with _committed() as session:
        rows = [
            _receipt_row(
                tenant_id,
                phase="completed",
                manifest_completed_at=_NOW,
                completed_at=_NOW,
            )
            for _ in range(count)
        ]
        session.add_all(rows)
        await session.flush()
        return sorted(row.id for row in rows)


async def _remaining(ids: list[UUID]) -> int:
    async with _committed() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionReceipts)
                .where(RetentionReceipts.id.in_(ids))
            )
            or 0
        )


def _runner(
    session: AsyncSession,
    *,
    chunk_rows: int = 500,
    budget_rows: int = 100_000,
    budget_seconds: float = 600,
    lock_timeout_ms: int = 2_000,
    clock: Callable[[], float] | None = None,
) -> RetentionRunner:
    return RetentionRunner(
        session=session,
        job_runs=RetentionJobRunRepository(session),
        audit_service=AuditService(repository=AuditLogRepositoryImpl(session)),
        budget=RetentionBudget(rows=budget_rows, files=100_000, seconds=budget_seconds),
        limits=RetentionChunkLimits(
            rows=chunk_rows,
            statement_timeout_ms=30_000,
            lock_timeout_ms=lock_timeout_ms,
            stale_after_seconds=3600,
        ),
        **({"clock": clock} if clock is not None else {}),
    )


async def _run(
    after_batch: Callable[[RetentionBatch], Awaitable[None]] | None = None,
    *,
    extra_steps: tuple[RetentionStep, ...] = (),
    counts: Callable[[int], Mapping[str, int]] = lambda n: {"deleted": n},
    **limits: Any,
) -> RetentionRunReport:
    async with sessionmanager.session() as session:
        task = _FakeTask(session, after_batch, extra_steps, counts)
        return await _runner(session, **limits).run(task)


async def _audits() -> list[AuditLogTable]:
    async with _committed() as session:
        audits = list(
            await session.scalars(
                sa.select(AuditLogTable)
                .where(
                    AuditLogTable.action.in_(
                        [
                            ActionType.GALLRING_APPLIED.value,
                            ActionType.GALLRING_SKIPPED.value,
                        ]
                    )
                )
                .order_by(AuditLogTable.timestamp)
            )
        )
        session.expunge_all()
        return audits


async def _claim(stale_after_seconds: int = 3600) -> UUID | None:
    async with _committed() as session:
        return await RetentionJobRunRepository(session).claim(
            task=_TASK, stale_after_seconds=stale_after_seconds
        )


async def _until_a_session_waits_on_a_lock() -> None:
    """Proves the concurrent statement reached the database and is blocked."""
    for _ in range(200):
        async with _committed() as session:
            waiting = await session.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database() "
                    "AND query ILIKE '%gallring_job_runs%'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the concurrent statement never waited on a lock")


async def _running_rows() -> int:
    async with _committed() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionJobRuns)
                .where(RetentionJobRuns.outcome == RetentionJobOutcome.RUNNING.value)
            )
            or 0
        )


class _JobRowHolder:
    """Another transaction that locks a job row and holds it until released."""

    def __init__(self, job_run_id: UUID) -> None:
        self.locked = asyncio.Event()
        self._release = asyncio.Event()
        self._holder = asyncio.create_task(self._hold(job_run_id))

    async def _hold(self, job_run_id: UUID) -> None:
        async with _committed() as session:
            await session.execute(
                sa.select(RetentionJobRuns.id)
                .where(RetentionJobRuns.id == job_run_id)
                .with_for_update()
            )
            self.locked.set()
            await self._release.wait()

    async def release(self) -> None:
        self._release.set()
        await self._holder


async def _make_stale(job_run_id: UUID) -> None:
    async with _committed() as session:
        await session.execute(
            sa.update(RetentionJobRuns)
            .where(RetentionJobRuns.id == job_run_id)
            .values(heartbeat_at=sa.func.now() - timedelta(hours=2))
        )


# Exclusive claim and ownership --------------------------------------------------


async def test_two_claims_at_once_leave_one_execution() -> None:
    async with sessionmanager.session() as first:
        async with first.begin():
            first_id = await RetentionJobRunRepository(first).claim(
                task=_TASK, stale_after_seconds=3600
            )
            second = asyncio.create_task(_claim())
            # The second insert waits on the partial unique index.
            await _until_a_session_waits_on_a_lock()
            assert not second.done()
        assert first_id is not None
    assert await second is None
    assert await _running_rows() == 1


async def test_stale_takeover_fences_the_superseded_execution() -> None:
    stale_id = await _claim()
    assert stale_id is not None
    await _make_stale(stale_id)

    replacement_id = await _claim(stale_after_seconds=3600)

    assert replacement_id not in (None, stale_id)
    async with _committed() as session:
        repo = RetentionJobRunRepository(session)
        assert await repo.renew(stale_id) is False
        assert (
            await repo.finish(
                stale_id, outcome=RetentionJobOutcome.SUCCEEDED, error_code=None
            )
            is False
        )
        superseded = await session.get(RetentionJobRuns, stale_id)
        assert superseded is not None
        assert superseded.outcome == RetentionJobOutcome.SUPERSEDED.value
    assert await _running_rows() == 1


async def test_renewed_execution_is_not_superseded() -> None:
    owner_id = await _claim()
    assert owner_id is not None
    # A fresh heartbeat is never taken over.
    assert await _claim(stale_after_seconds=3600) is None
    await _make_stale(owner_id)

    async with sessionmanager.session() as owner:
        async with owner.begin():
            # A chunk's first statement renews and keeps the row locked to commit.
            assert await RetentionJobRunRepository(owner).renew(owner_id)
            takeover = asyncio.create_task(_claim(stale_after_seconds=3600))
            await _until_a_session_waits_on_a_lock()
            assert not takeover.done()

    assert await takeover is None
    async with _committed() as session:
        owner_row = await session.get(RetentionJobRuns, owner_id)
        assert owner_row is not None
        assert owner_row.outcome == RetentionJobOutcome.RUNNING.value


async def test_superseded_runner_commits_no_further_chunk(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 3)
    takeovers: list[asyncio.Task[None]] = []

    async def supersede(job_run_id: UUID) -> None:
        async with _committed() as session:
            await session.execute(
                sa.update(RetentionJobRuns)
                .where(RetentionJobRuns.id == job_run_id)
                .values(
                    outcome=RetentionJobOutcome.SUPERSEDED.value,
                    finished_at=sa.func.now(),
                )
            )

    async def take_over_after_first_batch(batch: RetentionBatch) -> None:
        if batch.batch_seq == 1:
            # Another worker takes over while this chunk still holds the job row.
            takeovers.append(asyncio.create_task(supersede(batch.job_run_id)))
            await _until_a_session_waits_on_a_lock()

    report = await _run(take_over_after_first_batch, chunk_rows=1)

    await asyncio.gather(*takeovers)
    assert report.outcome == RetentionJobOutcome.SUPERSEDED
    assert await _remaining(items) == 2  # chunk 2 failed its ownership check
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, report.job_run_id)
        assert job is not None
        assert job.outcome == RetentionJobOutcome.SUPERSEDED.value


async def test_a_contended_claim_times_out_and_is_recorded() -> None:
    stale_id = await _claim()
    assert stale_id is not None
    await _make_stale(stale_id)
    holder = _JobRowHolder(stale_id)
    await holder.locked.wait()

    started = time.monotonic()
    try:
        # The takeover waits on the stale row's lock; the claim bounds the wait.
        report = await asyncio.wait_for(_run(lock_timeout_ms=200), timeout=20)
    finally:
        await holder.release()

    assert time.monotonic() - started < 5
    assert report.outcome == RetentionJobOutcome.SKIPPED
    assert report.error_code == RetentionErrorCode.CLAIM_TIMEOUT
    async with _committed() as session:
        rows = {
            row.id: (row.outcome, row.error_code)
            for row in await session.scalars(sa.select(RetentionJobRuns))
        }
    assert rows == {
        stale_id: (RetentionJobOutcome.RUNNING.value, None),
        report.job_run_id: (RetentionJobOutcome.SKIPPED.value, "claim_timeout"),
    }


async def test_a_contended_ownership_row_bounds_renew_and_finish(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 2)
    holders: list[_JobRowHolder] = []

    async def lock_after_this_chunk(batch: RetentionBatch) -> None:
        if batch.batch_seq == 1:
            holders.append(_JobRowHolder(batch.job_run_id))
            # Queued behind this chunk's ownership lock; it holds the row next.
            await _until_a_session_waits_on_a_lock()

    class _Contended(RetentionJobRunRepository):
        async def renew(self, job_run_id: UUID) -> bool:
            if holders:
                await holders[0].locked.wait()
            return await super().renew(job_run_id)

    started = time.monotonic()
    async with sessionmanager.session() as session:
        runner = _runner(session, chunk_rows=1, lock_timeout_ms=200)
        runner.job_runs = _Contended(session)
        try:
            report = await asyncio.wait_for(
                runner.run(_FakeTask(session, lock_after_this_chunk)), timeout=20
            )
        finally:
            for holder in holders:
                await holder.release()

    assert time.monotonic() - started < 5
    # Chunk 2's renew and then the finish timed out: the run kept chunk 1 only.
    assert report.outcome == RetentionJobOutcome.RUNNING
    assert report.error_code == RetentionErrorCode.FINISH_TIMEOUT
    assert report.counts == {"items.deleted": 1}
    assert await _remaining(items) == 1
    # The row keeps the recorded progress until the stale takeover records it.
    assert report.job_run_id is not None
    await _make_stale(report.job_run_id)
    assert await _claim() is not None
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, report.job_run_id)
        assert job is not None
        assert (job.outcome, job.batch_count, job.counts) == (
            RetentionJobOutcome.SUPERSEDED.value,
            1,
            {"items.deleted": 1},
        )


# Required audit, budgets and timeouts -------------------------------------------


async def test_audit_failure_rolls_back_the_batch_and_its_progress(
    test_tenant, monkeypatch
) -> None:
    items = await _work_items(test_tenant.id, 1)

    async def unavailable(self, audit_log):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create_if_absent", unavailable)

    report = await _run()

    assert report.outcome == RetentionJobOutcome.FAILED
    assert await _remaining(items) == 1
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, report.job_run_id)
        assert job is not None
        assert (job.batch_count, job.counts) == (0, {})


async def test_batch_audit_is_required_even_when_the_action_is_switched_off(
    test_tenant, monkeypatch
) -> None:
    await _work_items(test_tenant.id, 1)

    async def switched_off(self, tenant_id, action) -> bool:
        return False

    monkeypatch.setattr(AuditService, "_should_log_action", switched_off)

    await _run()

    assert len(await _audits()) == 1


async def test_effects_for_one_audit_tenant_are_one_event(test_tenant) -> None:
    async with _committed() as session:
        deployment_tenant_id = await RetentionJobRunRepository(
            session
        ).deployment_tenant_id()
    assert deployment_tenant_id is not None
    first, second = uuid4(), uuid4()

    async def deployment_and_tenant_effect(
        batch: RetentionBatch,
    ) -> RetentionStepResult:
        # A deployment-level effect and one in the deployment's own tenant share
        # the batch's audit identity.
        return RetentionStepResult(
            rows=2,
            effects=(
                RetentionTenantEffect(
                    tenant_id=None, counts={"deleted": 1}, receipt_ids=(first,)
                ),
                RetentionTenantEffect(
                    tenant_id=deployment_tenant_id,
                    counts={"confirmed": 1},
                    receipt_ids=(second,),
                ),
            ),
            exhausted=True,
        )

    await _run(
        extra_steps=(RetentionStep(name="both", run=deployment_and_tenant_effect),)
    )

    [audit] = [a for a in await _audits() if a.log_metadata.get("step") == "both"]
    assert audit.tenant_id == deployment_tenant_id
    assert audit.log_metadata["counts"] == {"deleted": 1, "confirmed": 1}
    assert audit.log_metadata["receipt_ids"] == [str(first), str(second)]


async def test_budget_stops_the_run_and_the_next_run_resumes(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 5)

    first = await _run(chunk_rows=2, budget_rows=3)
    second = await _run(chunk_rows=2, budget_rows=3)

    assert first.outcome == RetentionJobOutcome.PARTIAL
    assert first.counts == {"items.deleted": 3}
    assert second.outcome == RetentionJobOutcome.SUCCEEDED
    assert second.counts == {"items.deleted": 2}
    assert await _remaining(items) == 0
    audits = await _audits()
    # One audit per committed batch that deleted (2 + 1, then 2), its id derived
    # from the batch identity.
    assert len(audits) == 3
    for audit in audits:
        job_run_id = UUID(audit.log_metadata["job_run_id"])
        assert job_run_id in (first.job_run_id, second.job_run_id)
        assert audit.id == retention_batch_audit_id(
            job_run_id=job_run_id,
            batch_seq=audit.log_metadata["batch_seq"],
            tenant_id=test_tenant.id,
        )
    # Replaying a committed batch's audit returns the stored event.
    replayed = audits[0]
    async with _committed() as session:
        stored = await AuditService(repository=AuditLogRepositoryImpl(session)).log(
            audit_id=replayed.id,
            tenant_id=test_tenant.id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.GALLRING_APPLIED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=test_tenant.id,
            description="replay",
            metadata={},
            required=True,
        )
    assert stored is not None and stored.description == replayed.description
    assert len(await _audits()) == 3


async def test_seconds_budget_stops_the_run(test_tenant) -> None:
    await _work_items(test_tenant.id, 3)
    ticks = itertools.count()

    # The start and the first budget check read 0 s; the next check reads 11 s.
    report = await _run(
        chunk_rows=1,
        budget_seconds=10,
        clock=lambda: 0.0 if next(ticks) < 2 else 11.0,
    )

    assert report.outcome == RetentionJobOutcome.PARTIAL
    assert report.counts == {"items.deleted": 1}


async def test_a_lock_timeout_ends_the_run_as_partial_and_the_next_run_finishes(
    test_tenant,
) -> None:
    items = await _work_items(test_tenant.id, 2)

    async with sessionmanager.session() as holder:
        async with holder.begin():
            await holder.execute(
                sa.select(RetentionReceipts.id)
                .where(RetentionReceipts.id == items[0])
                .with_for_update()
            )
            blocked = await _run(lock_timeout_ms=200)

    assert blocked.outcome == RetentionJobOutcome.PARTIAL
    assert blocked.error_code == RetentionErrorCode.CHUNK_TIMEOUT
    assert await _remaining(items) == 2  # the chunk rolled back

    finished = await _run()

    assert finished.outcome == RetentionJobOutcome.SUCCEEDED
    assert await _remaining(items) == 0


async def test_a_timeout_another_error_wraps_still_ends_the_run_as_partial(
    test_tenant,
) -> None:
    async with _committed() as session:
        row = _receipt_row(test_tenant.id, phase="pending", category="template_asset")
        session.add(row)
        await session.flush()
        locked_id = row.id

    class _Busy(RuntimeError):
        """A lock helper's own error for a busy lock."""

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            sa.select(RetentionReceipts.id)
            .where(RetentionReceipts.id == locked_id)
            .with_for_update()
        )
        async with sessionmanager.session() as session:

            async def busy(batch: RetentionBatch) -> RetentionStepResult:
                try:
                    await session.execute(
                        sa.select(RetentionReceipts.id)
                        .where(RetentionReceipts.id == locked_id)
                        .with_for_update()
                    )
                except DBAPIError as exc:
                    raise _Busy("busy") from exc
                return RetentionStepResult(exhausted=True)

            task = _FakeTask(
                session, extra_steps=(RetentionStep(name="busy", run=busy),)
            )
            report = await _runner(session, lock_timeout_ms=200).run(task)

    assert report.outcome == RetentionJobOutcome.PARTIAL
    assert report.error_code == RetentionErrorCode.CHUNK_TIMEOUT


async def test_emergency_switch_skip_is_recorded_and_audited(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 1)

    for _ in range(2):
        async with sessionmanager.session() as session:
            report = await _runner(session).skip(_TASK)
        assert report.outcome == RetentionJobOutcome.SKIPPED

    assert await _remaining(items) == 1
    skips = [
        audit
        for audit in await _audits()
        if audit.log_metadata.get("reason") == "disabled_by_deployment_setting"
    ]
    # One required system event per suppressed run, in the deployment's tenant.
    assert len(skips) == 2
    assert {audit.actor_type for audit in skips} == {ActorType.SYSTEM.value}
    async with _committed() as session:
        outcomes = list(await session.scalars(sa.select(RetentionJobRuns.outcome)))
    assert outcomes == [RetentionJobOutcome.SKIPPED.value] * 2


# Every charged row is audited; durable step cursors ---------------------------------


async def test_an_item_only_pruning_chunk_writes_its_audit(
    test_tenant, monkeypatch
) -> None:
    receipt_id = await _receipt_with_items(
        test_tenant.id,
        5,
        phase="completed",
        manifest_completed_at=_NOW,
        completed_at=_NOW,
        pruning_started_at=_NOW,
    )

    async def run() -> RetentionRunReport:
        async with sessionmanager.session() as session:
            service = RetentionReceiptService(RetentionReceiptRepository(session))
            task = _Task(
                (RetentionStep(name="prune", run=service.prune_step),),
                count_keys=RECEIPT_PRUNING_COUNT_KEYS,
            )
            return await _runner(session, chunk_rows=2, budget_rows=2).run(task)

    # One chunk deletes two of the five items and leaves the receipt.
    first = await run()

    assert first.counts == {"prune.items_pruned": 2}
    assert await _stored_rows(receipt_id) == 4
    [audit] = await _audits()
    assert audit.log_metadata["counts"] == {"items_pruned": 2}
    assert audit.tenant_id == test_tenant.id

    async def unavailable(self, audit_log):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create_if_absent", unavailable)
    failed = await run()

    assert failed.outcome == RetentionJobOutcome.FAILED
    assert await _stored_rows(receipt_id) == 4  # the items' deletion rolled back
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, failed.job_run_id)
        assert job is not None and (job.batch_count, job.counts) == (0, {})


@pytest.mark.parametrize(
    "result",
    [
        # Deleted, charged and not reported.
        lambda batch: RetentionStepResult(rows=1, exhausted=True),
        # Deleted files, charged and not reported.
        lambda batch: RetentionStepResult(files=1, exhausted=True),
        # Charged more than the batch allows.
        lambda batch: RetentionStepResult(
            rows=batch.rows + 1,
            effects=(RetentionTenantEffect(tenant_id=None, counts={"deleted": 1}),),
            exhausted=True,
        ),
    ],
    ids=["unreported", "unreported_files", "overcharged"],
)
async def test_a_call_that_charges_unreported_or_excess_work_is_refused(
    test_tenant, result
) -> None:
    items = await _work_items(test_tenant.id, 1)

    async with sessionmanager.session() as session:

        async def delete_one(batch: RetentionBatch) -> RetentionStepResult:
            await session.execute(
                sa.delete(RetentionReceipts).where(RetentionReceipts.id == items[0])
            )
            return result(batch)

        report = await _runner(session, chunk_rows=1).run(
            _Task((RetentionStep(name="delete", run=delete_one),))
        )

    assert report.outcome == RetentionJobOutcome.FAILED
    assert await _remaining(items) == 1
    assert await _audits() == []


@pytest.mark.parametrize(
    ("charged", "charged_files", "outcome"),
    [(3, 0, "succeeded"), (4, 0, "failed"), (3, 1, "succeeded")],
)
@pytest.mark.parametrize("file_limit", [None, 0])
async def test_a_step_batch_bounds_its_calls_instead_of_the_chunk_size(
    test_tenant, charged, charged_files, outcome, file_limit
) -> None:
    """Kills M87: row-only steps can commit work charged to the file budget."""
    items = await _work_items(test_tenant.id, 1)
    batches: list[RetentionBatch] = []

    async with sessionmanager.session() as session:

        async def whole_unit(batch: RetentionBatch) -> RetentionStepResult:
            batches.append(batch)
            await session.execute(
                sa.delete(RetentionReceipts).where(RetentionReceipts.id == items[0])
            )
            return RetentionStepResult(
                rows=charged,
                files=charged_files,
                effects=(RetentionTenantEffect(tenant_id=None, counts={"deleted": 1}),),
                exhausted=True,
            )

        report = await _runner(session, chunk_rows=1).run(
            _Task(
                (
                    RetentionStep(
                        name="unit", run=whole_unit, max_batch=3, max_files=file_limit
                    ),
                )
            )
        )

    # The step's batch replaces the one-row chunk; more than it is refused.
    assert (batches[0].rows, batches[0].files) == (3, 3 if file_limit is None else 0)
    if file_limit == 0 and charged_files:
        outcome = "failed"
    assert report.outcome == RetentionJobOutcome(outcome)
    assert await _remaining(items) == (0 if outcome == "succeeded" else 1)


async def test_a_step_cursor_carries_a_pass_across_executions(test_tenant) -> None:
    # Three blocked rows before the one deletable row: a blocked prefix larger
    # than the two-row budget of one execution.
    async with _committed() as session:
        rows = [
            _receipt_row(
                test_tenant.id,
                phase="pending",
                category="template_asset" if index < 3 else "abandoned_upload",
                started_at=_NOW + timedelta(seconds=index),
            )
            for index in range(4)
        ]
        session.add_all(rows)
        await session.flush()
        blocked_ids = [row.id for row in rows[:3]]
        deletable_id = rows[3].id
    examined: list[list[UUID]] = []

    async def run() -> RetentionRunReport:
        async with sessionmanager.session() as session:

            async def scan(batch: RetentionBatch) -> RetentionStepResult:
                stmt = (
                    sa.select(
                        RetentionReceipts.started_at,
                        RetentionReceipts.id,
                        RetentionReceipts.category,
                    )
                    .where(RetentionReceipts.task == _TASK)
                    .order_by(RetentionReceipts.started_at, RetentionReceipts.id)
                    .limit(batch.rows)
                )
                if batch.cursor is not None:
                    stmt = stmt.where(
                        sa.tuple_(RetentionReceipts.started_at, RetentionReceipts.id)
                        > sa.tuple_(
                            sa.literal(batch.cursor.at), sa.literal(batch.cursor.id)
                        )
                    )
                page = list((await session.execute(stmt)).tuples())
                examined.append([row_id for _, row_id, _ in page])
                deletable = [i for _, i, c in page if c == "abandoned_upload"]
                if deletable:
                    await session.execute(
                        sa.delete(RetentionReceipts).where(
                            uuid_in(RetentionReceipts.id, deletable)
                        )
                    )
                return RetentionStepResult(
                    rows=len(page),
                    effects=(
                        (
                            RetentionTenantEffect(
                                tenant_id=test_tenant.id,
                                counts={"deleted": len(deletable)},
                            ),
                        )
                        if deletable
                        else ()
                    ),
                    blocked={"busy": len(page) - len(deletable)},
                    exhausted=len(page) < batch.rows,
                    cursor=RetentionKeyset(at=page[-1][0], id=page[-1][1])
                    if page
                    else None,
                )

            return await _runner(session, chunk_rows=2, budget_rows=2).run(
                _Task((RetentionStep(name="scan", run=scan),))
            )

    first = await run()
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, first.job_run_id)
        assert job is not None
        stored = job.cursors
    # A night the emergency switch suppressed does not restart the pass.
    async with sessionmanager.session() as session:
        await _runner(session).skip(_TASK)
    second = await run()
    third = await run()
    fourth = await run()

    assert first.outcome == RetentionJobOutcome.PARTIAL
    assert stored == {
        "scan": {
            "at": (_NOW + timedelta(seconds=1)).isoformat(),
            "id": str(blocked_ids[1]),
        }
    }
    # The second execution continues after the prefix and reaches the last row.
    assert examined[:2] == [blocked_ids[:2], [blocked_ids[2], deletable_id]]
    assert await _remaining([deletable_id]) == 0
    # The pass ends in the third execution, so the fourth starts a new one.
    assert (third.outcome, examined[2]) == (RetentionJobOutcome.SUCCEEDED, [])
    assert examined[3] == blocked_ids[:2]
    assert second.counts == {"scan.deleted": 1}
    assert fourth.blocked == {"scan.busy": 2}


async def test_a_stale_takeover_continues_from_the_superseded_cursors() -> None:
    position = RetentionKeyset(at=_NOW, id=uuid4(), item=7)
    stale_id = await _claim()
    assert stale_id is not None
    async with _committed() as session:
        await RetentionJobRunRepository(session).record_progress(
            stale_id, batch_count=1, counts={}, blocked={}, cursors={"scan": position}
        )
    await _make_stale(stale_id)

    replacement_id = await _claim()

    assert replacement_id is not None
    async with _committed() as session:
        cursors = await RetentionJobRunRepository(session).cursors(replacement_id)
    # The superseded execution committed its chunks; their positions hold.
    assert cursors == {"scan": position}


async def test_a_timed_out_chunk_keeps_the_cursor_of_the_last_commit(
    test_tenant,
) -> None:
    async with _committed() as session:
        rows = [
            _receipt_row(
                test_tenant.id,
                phase="pending",
                category="template_asset",
                started_at=_NOW + timedelta(seconds=index),
            )
            for index in range(4)
        ]
        session.add_all(rows)
        await session.flush()
        ids = [row.id for row in rows]

    async with sessionmanager.session() as holder, holder.begin():
        # The second page's first row is locked: that chunk times out.
        await holder.execute(
            sa.select(RetentionReceipts.id)
            .where(RetentionReceipts.id == ids[2])
            .with_for_update()
        )
        async with sessionmanager.session() as session:

            async def scan(batch: RetentionBatch) -> RetentionStepResult:
                stmt = (
                    sa.select(RetentionReceipts.started_at, RetentionReceipts.id)
                    .where(RetentionReceipts.task == _TASK)
                    .order_by(RetentionReceipts.started_at, RetentionReceipts.id)
                    .limit(batch.rows)
                    .with_for_update()
                )
                if batch.cursor is not None:
                    stmt = stmt.where(
                        sa.tuple_(RetentionReceipts.started_at, RetentionReceipts.id)
                        > sa.tuple_(
                            sa.literal(batch.cursor.at), sa.literal(batch.cursor.id)
                        )
                    )
                page = list((await session.execute(stmt)).tuples())
                return RetentionStepResult(
                    rows=len(page),
                    blocked={"busy": len(page)},
                    exhausted=len(page) < batch.rows,
                    cursor=RetentionKeyset(at=page[-1][0], id=page[-1][1]),
                )

            report = await _runner(session, chunk_rows=2, lock_timeout_ms=200).run(
                _Task((RetentionStep(name="scan", run=scan),))
            )

    assert report.error_code == RetentionErrorCode.CHUNK_TIMEOUT
    async with _committed() as session:
        cursors = await RetentionJobRunRepository(session).cursors(report.job_run_id)
    assert cursors == {
        "scan": RetentionKeyset(at=_NOW + timedelta(seconds=1), id=ids[1])
    }


async def test_a_skip_without_a_tenant_to_audit_it_is_refused(monkeypatch) -> None:
    async def no_tenant(self) -> None:
        return None

    monkeypatch.setattr(RetentionJobRunRepository, "deployment_tenant_id", no_tenant)

    async with sessionmanager.session() as session:
        with pytest.raises(RetentionContractError):
            await _runner(session).skip(_TASK)

    async with _committed() as session:
        assert list(await session.scalars(sa.select(RetentionJobRuns.id))) == []


# Physical tracking ----------------------------------------------------------------


async def _live_content(tenant_id: UUID, user_id: UUID) -> UUID:
    """A content row no file references any more but that is not deleted yet:
    the content owner keeps it, so its manifest item stays pending."""
    payload = uuid4().bytes
    key = f"gallring-{uuid4()}"
    async with _committed() as session:
        file = Files(
            name=f"gallring-{uuid4()}.txt",
            mimetype="text/plain",
            file_type=FileType.TEXT.value,
            owner_type="user",
            owner_user_id=user_id,
            owner_service_id=None,
            tenant_id=tenant_id,
        )
        session.add(file)
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
        content_id = content.id
    async with _committed() as session:
        await session.execute(
            sa.delete(FileContentReferences).where(
                FileContentReferences.content_id == content_id
            )
        )
    return content_id


async def test_physical_confirmation_continues_inside_a_receipt_the_next_night(
    test_tenant, admin_user
) -> None:
    # R1: three items whose content is still live; R2: an empty manifest.
    async with _committed() as session:
        r1 = _receipt_row(
            test_tenant.id,
            phase="completed",
            manifest_completed_at=_NOW,
            completed_at=_NOW,
        )
        r2 = _receipt_row(
            test_tenant.id,
            phase="completed",
            manifest_completed_at=_NOW,
            completed_at=_NOW + timedelta(seconds=1),
        )
        session.add_all([r1, r2])
        await session.flush()
        r1_id, r2_id = r1.id, r2.id
    for _ in range(3):
        content_id = await _live_content(test_tenant.id, admin_user.id)
        async with _committed() as session:
            session.add(
                RetentionReceiptItems(
                    receipt_id=r1_id, file_id=uuid4(), content_id=content_id
                )
            )

    async def night() -> RetentionRunReport:
        async with sessionmanager.session() as session:
            service = RetentionReceiptService(RetentionReceiptRepository(session))
            task = _Task(
                (RetentionStep(name="physical", run=service.physical_step),),
                count_keys=PHYSICAL_CONFIRMATION_COUNT_KEYS,
                blocked_keys=PHYSICAL_CONFIRMATION_BLOCKED_KEYS,
            )
            return await _runner(session, chunk_rows=2, budget_rows=2).run(task)

    nights = [await night() for _ in range(3)]

    # Two rows a night: items 1-2, then item 3 and R1 finished, then R2.
    assert [report.counts.get("physical.items_examined", 0) for report in nights] == [
        2,
        1,
        0,
    ]
    async with _committed() as session:
        r2_row = await session.get(RetentionReceipts, r2_id)
        assert r2_row is not None and r2_row.physical_confirmed_at is not None
        r1_row = await session.get(RetentionReceipts, r1_id)
        assert r1_row is not None and r1_row.physical_confirmed_at is None


async def test_physical_confirmation_waits_for_a_complete_manifest(test_tenant) -> None:
    states = {
        "completed": {"phase": "completed", "completed_at": _NOW},
        "deleting": {"phase": "deleting"},
        "pending": {"phase": "pending"},
    }
    receipt_ids: dict[str, UUID] = {}
    async with _committed() as session:
        for name, values in states.items():
            receipt = _receipt_row(
                test_tenant.id,
                manifest_completed_at=_NOW if name != "pending" else None,
                **values,
            )
            session.add(receipt)
            await session.flush()
            receipt_ids[name] = receipt.id

    async with _committed() as session:
        await RetentionReceiptService(
            RetentionReceiptRepository(session)
        ).confirm_physical(budget=100, cursor=None)

    async with _committed() as session:
        confirmed = set()
        for name, receipt_id in receipt_ids.items():
            receipt = await session.get(RetentionReceipts, receipt_id)
            assert receipt is not None
            if receipt.physical_confirmed_at is not None:
                confirmed.add(name)
    # Empty manifests: only the completed receipt's enumeration is final.
    assert confirmed == {"completed"}


async def _receipt_with_items(tenant_id: UUID, items: int, **values: Any) -> UUID:
    async with _committed() as session:
        receipt = _receipt_row(tenant_id, **values)
        session.add(receipt)
        await session.flush()
        session.add_all(
            RetentionReceiptItems(
                receipt_id=receipt.id, file_id=uuid4(), content_id=uuid4()
            )
            for _ in range(items)
        )
        return receipt.id


async def _stored_rows(receipt_id: UUID) -> int:
    """The receipt's own row and its manifest items still stored."""
    async with _committed() as session:
        receipts = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RetentionReceipts)
            .where(RetentionReceipts.id == receipt_id)
        )
        items = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RetentionReceiptItems)
            .where(RetentionReceiptItems.receipt_id == receipt_id)
        )
        return int(receipts or 0) + int(items or 0)


async def _prune(limit: int) -> PrunedReceipts:
    async with _committed() as session:
        return await RetentionReceiptService(RetentionReceiptRepository(session)).prune(
            limit=limit
        )


async def test_a_manifest_larger_than_the_budget_is_pruned_across_chunks(
    test_tenant,
) -> None:
    expired = _NOW - timedelta(days=4000)
    receipt_id = await _receipt_with_items(
        test_tenant.id,
        5,
        phase="completed",
        manifest_completed_at=expired,
        completed_at=expired,
    )
    calls: list[tuple[int, int]] = []
    pruned: list[tuple[UUID, UUID]] = []

    while True:
        before = await _stored_rows(receipt_id)
        result = await _prune(limit=2)
        if result.rows == 0:
            break
        calls.append((result.rows, before - await _stored_rows(receipt_id)))
        pruned.extend(result.receipts)
        if len(calls) == 2:
            # Partly pruned: its remaining items are never confirmed as proof.
            async with _committed() as session:
                confirmation, _ = await RetentionReceiptService(
                    RetentionReceiptRepository(session)
                ).confirm_physical(budget=100, cursor=None)
            assert confirmation.items_examined == 0

    # Every call stays within its budget; the receipt goes after its 5 items.
    assert all(deleted <= rows <= 2 for rows, deleted in calls)
    assert sum(deleted for _, deleted in calls) == 6
    assert pruned == [(receipt_id, test_tenant.id)]


async def test_a_withdrawn_receipt_stops_covering_its_entity_and_is_pruned(
    test_tenant,
) -> None:
    family = NewRetentionReceipt(
        task=_TASK,
        entity_kind=RetentionEntityKind.FILE_FAMILY,
        entity_id=uuid4(),
        category=RetentionCategory.ABANDONED_UPLOAD,
        tenant_id=test_tenant.id,
    )
    async with _committed() as session:
        service = RetentionReceiptService(RetentionReceiptRepository(session))
        receipt = await service.append_manifest(
            await service.open(family),
            [(uuid4(), uuid4()) for _ in range(3)],
            manifest_after=ManifestPosition(file_id=uuid4(), variant="file", ordinal=0),
            complete=False,
        )
        await service.withdraw(receipt)

    async with _committed() as session:
        service = RetentionReceiptService(RetentionReceiptRepository(session))
        assert await service.lock(receipt.id) is None
        assert await service.unfinished(task=_TASK, after=None, limit=10) == []
        reopened = await service.open(family)
    assert reopened.id != receipt.id

    results = [await _prune(limit=2) for _ in range(3)]

    # Withdrawing wrote one row; the 3 items and the receipt go within budget.
    assert [result.rows for result in results] == [2, 2, 0]
    assert results[1].receipts == ((receipt.id, test_tenant.id),)
    assert await _stored_rows(receipt.id) == 0
    assert await _stored_rows(reopened.id) == 1


async def test_physical_confirmation_charges_items_and_receipts_from_one_budget(
    test_tenant,
) -> None:
    receipt_ids = [
        await _receipt_with_items(
            test_tenant.id,
            items,
            phase="completed",
            manifest_completed_at=_NOW,
            completed_at=_NOW + timedelta(seconds=index),
        )
        for index, items in enumerate((1, 0, 1))
    ]
    cursor = None
    charged: list[int] = []
    for _ in range(20):
        async with _committed() as session:
            confirmation, cursor = await RetentionReceiptService(
                RetentionReceiptRepository(session)
            ).confirm_physical(budget=2, cursor=cursor)
        charged.append(confirmation.items_examined + confirmation.receipts_examined)
        if cursor is None:
            break

    # Each item and each finished receipt is one row of the two-row budget.
    assert charged == [2, 2, 1]
    async with _committed() as session:
        confirmed = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RetentionReceipts)
            .where(
                uuid_in(RetentionReceipts.id, receipt_ids),
                RetentionReceipts.physical_confirmed_at.is_not(None),
            )
        )
    assert confirmed == 3


# Step invariants and the content-free proof ---------------------------------------


@dataclass
class _Captured:
    result: Any
    selects: list[tuple[str, Any]]


async def _selects_during(work: Awaitable[Any]) -> _Captured:
    """Run `work`, keeping the SELECT statements it sent, with their parameters."""
    selects: list[tuple[str, Any]] = []
    engine = sessionmanager._engine  # noqa: SLF001
    assert engine is not None

    def keep(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", keep)
    try:
        result = await work
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", keep)
    return _Captured(result=result, selects=selects)


async def test_a_step_call_without_progress_ends_that_step_only(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 2)
    calls: list[int] = []

    async def no_progress(batch: RetentionBatch) -> RetentionStepResult:
        calls.append(batch.batch_seq)
        return RetentionStepResult()  # nothing visited, not exhausted

    report = await _run(
        extra_steps=(
            RetentionStep(name="stuck", run=no_progress),
            RetentionStep(name="after", run=no_progress),
        )
    )

    # Each stalled step is called once, recorded, and the run goes on.
    assert len(calls) == 2
    assert report.outcome == RetentionJobOutcome.PARTIAL
    assert report.counts == {"items.deleted": 2, "stuck.stalled": 1, "after.stalled": 1}
    assert await _remaining(items) == 0
    async with _committed() as session:
        job = await session.get(RetentionJobRuns, report.job_run_id)
        assert job is not None and job.counts == report.counts


async def test_a_count_outside_the_task_names_is_refused(test_tenant) -> None:
    items = await _work_items(test_tenant.id, 1)

    report = await _run(counts=lambda n: {"Lönelista Anna.pdf": n})

    assert report.outcome == RetentionJobOutcome.FAILED
    assert await _remaining(items) == 1  # the chunk rolled back
    assert await _audits() == []


@pytest.mark.parametrize(("charge", "exhausted"), [(0, False), (2, False), (2, True)])
async def test_deferral_commits_proof_and_cursor_before_the_next_step(
    test_tenant, charge, exhausted
) -> None:
    """Kills M85 (defer repeats/stalls or loses audit) and M86 (defer+exhausted accepted)."""
    items = await _work_items(test_tenant.id, 3)
    position = RetentionKeyset(at=_NOW, id=items[0])
    async with sessionmanager.session() as session:

        async def before(batch: RetentionBatch) -> RetentionStepResult:
            effects = ()
            if charge:
                deleted = list(
                    await session.scalars(
                        sa.delete(RetentionReceipts)
                        .where(RetentionReceipts.id == items[0])
                        .returning(RetentionReceipts.id)
                    )
                )
                effects = (
                    RetentionTenantEffect(test_tenant.id, {"deleted": len(deleted)}),
                )
            return RetentionStepResult(
                rows=charge,
                effects=effects,
                deferred=True,
                exhausted=exhausted,
                cursor=position,
            )

        async def after(batch: RetentionBatch) -> RetentionStepResult:
            deleted = list(
                await session.scalars(
                    sa.delete(RetentionReceipts)
                    .where(RetentionReceipts.id == items[1])
                    .returning(RetentionReceipts.id)
                )
            )
            return RetentionStepResult(
                rows=2,
                exhausted=True,
                effects=(
                    RetentionTenantEffect(test_tenant.id, {"deleted": len(deleted)}),
                ),
            )

        report = await _runner(session).run(
            _Task(
                (
                    RetentionStep("before", before),
                    RetentionStep("after", after),
                )
            )
        )
    if exhausted:
        assert report.outcome == RetentionJobOutcome.FAILED
        assert await _remaining(items) == 3
        assert await _audits() == []
        return
    assert report.outcome == RetentionJobOutcome.PARTIAL
    assert report.counts.get("before.deferred") == 1
    assert "before.stalled" not in report.counts
    assert report.counts["after.deleted"] == 1
    assert await _remaining(items) == (1 if charge else 2)
    assert report.job_run_id is not None
    async with _committed() as session:
        assert await RetentionJobRunRepository(session).cursors(report.job_run_id) == {
            "before": position
        }
    audits = [a for a in await _audits() if a.log_metadata["step"] == "before"]
    assert len(audits) == 1 and audits[0].log_metadata["blocked"] == {"deferred": 1}


@pytest.mark.parametrize(
    "case",
    [
        "row_only",
        "over_rows",
        "over_files",
        "zero_rows",
        "nonfresh_fit",
        "fresh_fit",
        "continue",
    ],
)
async def test_collected_units_preserve_admission_cursor_and_committed_work(
    test_tenant, case
) -> None:
    """Kills M88 zero-file stall, M89/90 bad unit admission, M91 fit routing, M92 lost continuation."""
    items = await _work_items(test_tenant.id, 3)
    failed = case in {"over_rows", "over_files", "zero_rows"}
    async with sessionmanager.session() as session:

        async def collect(batch: RetentionBatch) -> RetentionStepResult:
            out = RetentionEffects()

            async def next_candidate(after: RetentionKeyset | None):
                index = 0 if after is None else items.index(after.id) + 1
                if index == len(items):
                    return None
                item = items[index]

                async def handle(rows: int, files: int) -> RetentionUnitUsage:
                    needed = (
                        5
                        if (
                            (case == "nonfresh_fit" and index == 1)
                            or (case == "fresh_fit" and index == 0)
                        )
                        else 2
                    )
                    if needed > rows:
                        out.blocked["busy"] += 1
                        return RetentionUnitUsage(
                            1, 0, RetentionUnitDisposition.DOES_NOT_FIT
                        )
                    if case == "continue" and index == 0:
                        changed = list(
                            await session.scalars(
                                sa.update(RetentionReceipts)
                                .where(
                                    RetentionReceipts.id == item,
                                    RetentionReceipts.physical_confirmed_at.is_(None),
                                )
                                .values(physical_confirmed_at=_NOW)
                                .returning(RetentionReceipts.id)
                            )
                        )
                        if changed:
                            out.add(test_tenant.id, "confirmed", len(changed))
                            return RetentionUnitUsage(
                                2, 0, RetentionUnitDisposition.CONTINUE
                            )
                    deleted = list(
                        await session.scalars(
                            sa.delete(RetentionReceipts)
                            .where(RetentionReceipts.id == item)
                            .returning(RetentionReceipts.id)
                        )
                    )
                    out.add(test_tenant.id, "deleted", len(deleted))
                    if index == 1:
                        if case == "over_rows":
                            return RetentionUnitUsage(rows + 1, 0)
                        if case == "over_files":
                            return RetentionUnitUsage(needed, files + 1)
                        if case == "zero_rows":
                            return RetentionUnitUsage(0, 0)
                    return RetentionUnitUsage(needed, 0)

                return RetentionKeyset(
                    at=_NOW + timedelta(seconds=index), id=item
                ), handle

            return await gather_retention_units(
                batch, next_candidate, out, chunk_rows=4, gather_seconds=10
            )

        task = _Task(
            (
                RetentionStep(
                    "units",
                    collect,
                    max_batch=8,
                    max_files=0 if case == "row_only" else None,
                ),
            ),
            count_keys=frozenset({"deleted", "confirmed"}),
        )
        report = await _runner(
            session, budget_rows=4 if case == "fresh_fit" else 16
        ).run(task)
        if case == "fresh_fit":
            assert report.outcome == RetentionJobOutcome.PARTIAL
            assert await _remaining(items) == 3
            assert report.counts["units.deferred"] == 1
            report = await _runner(session, budget_rows=16).run(task)
    assert report.outcome == (
        RetentionJobOutcome.FAILED if failed else RetentionJobOutcome.SUCCEEDED
    )
    assert await _remaining(items) == (3 if failed else 0)
    if failed:
        assert await _audits() == []
        assert report.job_run_id is not None
        async with _committed() as session:
            assert (
                await RetentionJobRunRepository(session).cursors(report.job_run_id)
                == {}
            )
    else:
        assert report.counts["units.deleted"] == 3
        if case == "continue":
            assert report.counts["units.confirmed"] == 1


async def test_gallring_audits_carry_only_allowlisted_metadata(test_tenant) -> None:
    await _work_items(test_tenant.id, 2)
    await _run(chunk_rows=1)
    async with sessionmanager.session() as session:
        await _runner(session).skip(_TASK)

    audits = await _audits()

    assert {audit.action for audit in audits} == {
        ActionType.GALLRING_APPLIED.value,
        ActionType.GALLRING_SKIPPED.value,
    }
    allowed = {"task", "step", "job_run_id", "batch_seq", "counts", "blocked"}
    allowed |= {"receipt_ids"}
    allowed |= {"reason", "actor"}
    for audit in audits:
        assert set(audit.log_metadata) <= allowed


async def test_a_receipt_resume_point_is_a_file_id_never_a_name(test_tenant) -> None:
    async with _committed() as session:
        service = RetentionReceiptService(RetentionReceiptRepository(session))
        receipt = await service.open(
            NewRetentionReceipt(
                task=_TASK,
                entity_kind=RetentionEntityKind.FILE_FAMILY,
                entity_id=uuid4(),
                category=RetentionCategory.ABANDONED_UPLOAD,
                tenant_id=test_tenant.id,
            )
        )
        with pytest.raises(TypeError):
            await service.append_manifest(
                receipt,
                [],
                manifest_after=cast(ManifestPosition, "Lönelista Anna.pdf"),
                complete=False,
            )
    with pytest.raises(ValueError):
        ManifestPosition(file_id=uuid4(), variant="Lönelista Anna.pdf", ordinal=0)
    with pytest.raises(ValueError):
        NewRetentionReceipt(
            task="Lönelista Anna",
            entity_kind=RetentionEntityKind.FILE_FAMILY,
            entity_id=uuid4(),
            category=RetentionCategory.ABANDONED_UPLOAD,
            tenant_id=test_tenant.id,
        )


async def test_pruning_is_bounded_by_the_deployment_audit_retention(
    test_tenant,
) -> None:
    async with _committed() as session:
        await session.execute(
            sa.delete(AuditRetentionPolicy).where(
                AuditRetentionPolicy.tenant_id == test_tenant.id
            )
        )
        session.add(AuditRetentionPolicy(tenant_id=test_tenant.id, retention_days=2555))
        # 2 000 final receipts one to five years old: kept by a seven-year window.
        await session.execute(
            sa.text(
                "INSERT INTO gallring_receipts (task, entity_kind, entity_id, "
                "category, trigger, tenant_id, phase, started_at, updated_at, "
                "manifest_completed_at, completed_at) "
                "SELECT :task, 'file_family', gen_random_uuid(), 'abandoned_upload', "
                "'scheduled', :tenant, 'completed', ts, ts, ts, ts FROM (SELECT now() "
                "- make_interval(days => 365 + g % 1500) AS ts "
                "FROM generate_series(1, 2000) g) s"
            ),
            {"task": _TASK, "tenant": test_tenant.id},
        )
        expired = _receipt_row(
            test_tenant.id,
            phase="completed",
            manifest_completed_at=_NOW - timedelta(days=2600),
            completed_at=_NOW - timedelta(days=2600),
        )
        session.add(expired)
        await session.flush()
        expired_id = expired.id
    async with _committed() as session:
        await session.execute(sa.text("ANALYZE gallring_receipts"))

    async with _committed() as session:
        statements = await _selects_during(
            RetentionReceiptRepository(session).prune(limit=500)
        )
    pruned = (await _prune(limit=500)).receipts
    async with _committed() as session:
        connection = await session.connection()
        statement, parameters = next(
            select for select in statements.selects if "make_interval" in select[0]
        )
        plan = "\n".join(
            row[0]
            for row in await connection.exec_driver_sql(
                "EXPLAIN ANALYZE " + statement, parameters
            )
        )

    # The first call marked the expired receipt, the next one deleted it.
    assert statements.result.rows == 1
    assert [receipt_id for receipt_id, _ in pruned] == [expired_id]
    # One literal cutoff from the deployment's window: the index scan visits only
    # the expired receipt, none of the 2 000 kept ones.
    assert "ix_gallring_receipts_completed_at" in plan
    assert "Rows Removed by Filter" not in plan
