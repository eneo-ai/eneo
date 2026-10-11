"""Conversation page charging, retry and deadline rules, without a database.

The real-PostgreSQL proof bound and the file-family admission are covered in
test_data_retention_hierarchical.py and test_unused_file_cleanup.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_history_retention_task import (
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.conversation_retention import (
    ConversationBlockReason,
    ConversationDeletion,
    ConversationPage,
    ConversationRootCostEstimate,
    ConversationRootKind,
    ConversationUnitResult,
    conversation_page_allocation,
    is_past_owner,
    past_owner,
    run_conversation_page,
)
from eneo.data_retention.application.retention_runner import RetentionBatch
from eneo.data_retention.domain.conversation_policy import ConversationPolicySource
from eneo.data_retention.domain.retention import RetentionKeyset

_STARTED = datetime(2026, 1, 1, tzinfo=timezone.utc)
_OWNER = UUID(int=1)


@dataclass
class _Root:
    keyset: RetentionKeyset
    children: int
    # Rows the root DELETE and its Files work charge together.
    unit_rows: int = 1


@dataclass
class _Pages:
    """Owner pages and keyset pages over their roots, like the repository;
    deleting a root removes it from later pages."""

    roots: list[_Root]
    kind: ConversationRootKind = ConversationRootKind.QUESTION
    # Owners with a policy, with or without due roots.
    owners: list[UUID] = field(default_factory=lambda: [_OWNER])
    now: list[float] = field(default_factory=lambda: [0.0])
    # Time each lock or delete statement takes on the fake clock.
    seconds_per_call: float = 0.0
    # The page size each lock_due_page call asked for.
    limits: list[int] = field(default_factory=list[int])
    proofs: list[tuple[UUID, int]] = field(default_factory=list[tuple[UUID, int]])
    deleted: list[UUID] = field(default_factory=list[UUID])

    def clock(self) -> float:
        return self.now[0]

    def _root(self, identifier: UUID) -> _Root:
        return next(root for root in self.roots if root.keyset.id == identifier)

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        self.now[0] += self.seconds_per_call
        self.limits.append(limit)
        owners = sorted(self.owners)
        if cursor is not None:
            assert cursor.group is not None
            owners = [
                owner
                for owner in owners
                if owner > cursor.group
                or (owner == cursor.group and not is_past_owner(cursor))
            ]
        page = owners[:limit]
        after = [
            root.keyset
            for root in sorted(
                self.roots, key=lambda root: (root.keyset.group, root.keyset.at)
            )
            if root.keyset.group in page
            and (
                cursor is None
                or root.keyset.group != cursor.group
                or root.keyset.at > cursor.at
            )
        ][:limit]
        return ConversationPage(
            roots=tuple(after),
            locked_ids=tuple(root.id for root in after),
            owners_probed=len(page),
            last_owner=page[-1] if page else None,
        )

    async def cascade_cost(self, identifier: UUID, ceiling: int) -> int:
        self.proofs.append((identifier, ceiling))
        return min(self._root(identifier).children, ceiling + 1)

    async def delete_unit(
        self,
        identifier: UUID,
        *,
        child_rows: int,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> ConversationUnitResult:
        root = self._root(identifier)
        self.now[0] += self.seconds_per_call
        if root.unit_rows > max_rows:
            # Like a File family refused for budget: the root DELETE is undone.
            return ConversationUnitResult(rows=1, files=0, fits=False)
        self.roots.remove(root)
        self.deleted.append(identifier)
        return ConversationUnitResult(
            rows=root.unit_rows,
            files=0,
            deletion=ConversationDeletion(
                id=identifier, tenant_id=uuid4(), source=ConversationPolicySource.SPACE
            ),
        )


def _roots(*shapes: tuple[int, int], owner: UUID = _OWNER) -> list[_Root]:
    return [
        _Root(
            keyset=RetentionKeyset(
                at=_STARTED + timedelta(minutes=index), id=uuid4(), group=owner
            ),
            children=children,
            unit_rows=unit_rows,
        )
        for index, (children, unit_rows) in enumerate(shapes)
    ]


def _batch(rows: int, cursor: RetentionKeyset | None, deadline: float = 60.0):
    return RetentionBatch(
        job_run_id=uuid4(),
        batch_seq=1,
        rows=rows,
        files=10,
        deadline=deadline,
        cursor=cursor,
    )


def _allocation(*, unit_rows: int, chunk_rows: int):
    return conversation_page_allocation(
        unit_rows=unit_rows,
        chunk_rows=chunk_rows,
        execution_rows=1000,
        execution_files=10,
        family_rows=5,
    )


@pytest.mark.asyncio
async def test_an_oversized_root_is_charged_its_bounded_proof_and_passed() -> None:
    """Mutants: the proof rows are not charged; the proof is not bounded by
    the remaining unit allowance; an oversized root stops the page."""
    big, small = _roots((1000, 1), (0, 1))
    pages = _Pages(roots=[big, small])
    allocation = _allocation(unit_rows=10, chunk_rows=30)

    result = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    # Discovery of 1 owner and 2 roots, the big root's proof stops at
    # ceiling + 1 = 10, then 1 row to delete the small root.
    assert pages.proofs == [(big.keyset.id, 9), (small.keyset.id, 9)]
    assert result.rows == 1 + 2 + 10 + 1
    assert result.blocked == {ConversationBlockReason.UNIT_EXCEEDS_BUDGET.value: 1}
    assert pages.deleted == [small.keyset.id]
    assert result.cursor == past_owner(_OWNER)
    assert result.exhausted


@pytest.mark.asyncio
async def test_a_root_short_of_the_chunk_remainder_is_retried_fresh() -> None:
    """Mutant: a root that only lacks the chunk's remaining allowance is
    blocked as oversized and passed instead of retried in a fresh chunk."""
    first, second = _roots((0, 3), (7, 2))
    pages = _Pages(roots=[first, second])
    allocation = _allocation(unit_rows=10, chunk_rows=12)
    estimate = ConversationRootCostEstimate()

    shortage = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None),
        allocation,
        estimate,
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    # 3 discovery + 3 for the first root leave 6 of the 12-row chunk: the
    # second root's 7 children exceed its ceiling of 5.
    assert shortage.rows == 3 + 3 + 6
    assert shortage.blocked == {}
    assert not shortage.deferred and not shortage.exhausted
    assert shortage.cursor == first.keyset
    assert pages.deleted == [first.keyset.id]

    retried = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, shortage.cursor),
        allocation,
        estimate,
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    assert retried.rows == 2 + 7 + 2
    assert retried.blocked == {}
    assert pages.deleted == [first.keyset.id, second.keyset.id]
    # The estimated page of one root is full, so the cursor stays at that root.
    assert retried.cursor == second.keyset


@pytest.mark.asyncio
async def test_the_deadline_stops_admission_after_the_first_root() -> None:
    """Mutants: the execution deadline is ignored; the deadline also stops the
    first root, so a late chunk makes no progress."""
    roots = _roots((0, 1), (0, 1), (0, 1))
    # The page lock alone passes the deadline; the first root still runs.
    pages = _Pages(roots=list(roots), seconds_per_call=10.0)
    allocation = _allocation(unit_rows=10, chunk_rows=30)

    result = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None, deadline=5.0),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    assert pages.deleted == [roots[0].keyset.id]
    assert result.cursor == roots[0].keyset
    assert result.rows == 1 + 3 + 1
    assert not result.deferred and not result.exhausted


@pytest.mark.asyncio
async def test_time_spent_before_the_page_counts_against_the_deadline() -> None:
    """Mutant: the deadline is measured from a clock started when the step is
    called, after the chunk waited for its transaction and lease renewal, so
    cheap roots keep being admitted past the execution's end."""
    roots = _roots((0, 1), (0, 1), (0, 1))
    # The renewal wait already used 4 of the 5 seconds; the first root uses
    # the rest.
    pages = _Pages(roots=list(roots), now=[4.0], seconds_per_call=0.5)
    allocation = _allocation(unit_rows=10, chunk_rows=30)

    result = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None, deadline=5.0),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    assert pages.deleted == [roots[0].keyset.id]
    assert not result.exhausted


@pytest.mark.asyncio
async def test_the_gather_window_stops_admission_before_the_deadline() -> None:
    """Mutant: the page admits roots until the execution deadline only, so its
    root locks are held for the whole remaining execution time."""
    roots = _roots((0, 1), (0, 1), (0, 1))
    pages = _Pages(roots=list(roots), seconds_per_call=0.6)
    allocation = _allocation(unit_rows=10, chunk_rows=30)

    result = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=1.0,
        clock=pages.clock,
    )

    # The lock and the first root take 1.2 of the 1.0 seconds; the deadline is 60.
    assert pages.deleted == [roots[0].keyset.id]
    assert result.cursor == roots[0].keyset
    assert not result.deferred and not result.exhausted


@pytest.mark.asyncio
async def test_an_expensive_chunk_shrinks_the_next_page() -> None:
    """Mutant: the cost estimate is never updated, so after roots that cost six rows each
    the next chunk still locks a page sized for the cheapest root."""
    roots = _roots(*((4, 1),) * 12)
    pages = _Pages(roots=list(roots))
    allocation = _allocation(unit_rows=10, chunk_rows=30)
    estimate = ConversationRootCostEstimate()

    first = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None),
        allocation,
        estimate,
        gather_seconds=math.inf,
        clock=pages.clock,
    )
    await run_conversation_page(
        pages,
        _batch(allocation.max_batch, first.cursor),
        allocation,
        estimate,
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    # One owner and ten locked roots, three deletions of five rows and the
    # fourth root's proof fill the 30-row chunk: 30 rows over 3 visited roots
    # is an estimate of 10, so 30 // 10 = 3 roots next.
    assert first.rows == 30
    assert pages.limits == [10, 3]


@pytest.mark.asyncio
async def test_probed_owners_are_charged_and_a_full_owner_page_continues() -> None:
    """Mutants: probed owners are not charged; exhaustion is decided by the
    root count, so a page of owners without due roots ends the pass; an owner
    without roots is probed again instead of passed."""
    empty = [UUID(int=2), UUID(int=3)]
    later = UUID(int=4)
    (due,) = _roots((0, 1), owner=later)
    pages = _Pages(roots=[due], owners=[*empty, later])
    allocation = _allocation(unit_rows=10, chunk_rows=6)

    first = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, None),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    # A page of two owners, neither with a due root.
    assert pages.limits == [2]
    assert first.rows == 2
    assert first.cursor == past_owner(empty[-1])
    assert not first.exhausted and not first.deferred

    second = await run_conversation_page(
        pages,
        _batch(allocation.max_batch, first.cursor),
        allocation,
        ConversationRootCostEstimate(),
        gather_seconds=math.inf,
        clock=pages.clock,
    )

    assert pages.deleted == [due.keyset.id]
    assert second.rows == 1 + 1 + 1
    assert second.exhausted


def test_every_history_step_goes_first_on_some_date() -> None:
    """Mutant: a step is left out of the date rotation (app runs after
    questions, which a standing backlog never lets run)."""
    allocation = _allocation(unit_rows=10, chunk_rows=30)
    orders: list[Sequence[str]] = []
    for offset in range(2):
        task = ConversationHistoryRetentionTask(
            AsyncSession(),
            allocation=allocation,
            now=datetime.combine(
                date(2026, 3, 1) + timedelta(days=offset),
                datetime.min.time(),
                tzinfo=timezone.utc,
            ),
            overdue_window=timedelta(days=1),
            overdue_rows=10,
            overdue_owner_rows=1000,
            gather_seconds=1.0,
        )
        orders.append([step.name for step in task.steps()])

    assert {order[0] for order in orders} == {"questions", "app_runs"}
    assert all(sorted(order) == sorted(orders[0]) for order in orders)
