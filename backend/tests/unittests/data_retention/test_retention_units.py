import math
from datetime import datetime, timezone
from uuid import UUID

import pytest

from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionKeyset

_POSITIONS = tuple(
    RetentionKeyset(at=datetime(2026, 1, 1, tzinfo=timezone.utc), id=UUID(int=n))
    for n in range(1, 4)
)


@pytest.mark.parametrize(
    "max_rows,max_files,chunk_rows,needs,file_charge,calls,rows,deleted,exhausted,deferred,cursor",
    [
        pytest.param(10, 0, 10, 2, 0, 4, 6, 3, True, False, 2, id="row-only"),
        pytest.param(4, 0, 4, 2, 0, 2, 4, 2, False, False, 1, id="discovery-row"),
        pytest.param(10, 1, 10, 2, 1, 1, 2, 1, False, False, 0, id="file-budget"),
        pytest.param(8, 0, 2, 6, 0, 1, 6, 1, False, False, 0, id="fresh-uses-batch"),
        pytest.param(8, 0, 4, 3, 0, 2, 4, 1, False, False, 0, id="later-retries"),
        pytest.param(2, 0, 4, 3, 0, 1, 1, 0, False, True, None, id="fresh-defers"),
    ],
)
async def test_units_are_admitted_within_the_batch_and_chunk(
    max_rows: int,
    max_files: int,
    chunk_rows: int,
    needs: int,
    file_charge: int,
    calls: int,
    rows: int,
    deleted: int,
    exhausted: bool,
    deferred: bool,
    cursor: int | None,
) -> None:
    """Kills M99 selecting a candidate without a row for its discovery, M100
    routing a fresh unit to the chunk allowance (or deferring a later one) and
    M101 stopping a row-only consumer on its zero file allowance."""
    selected: list[RetentionKeyset | None] = []
    out = RetentionEffects()

    async def next_candidate(
        after: RetentionKeyset | None,
    ) -> RetentionUnitCandidate | None:
        selected.append(after)
        index = 0 if after is None else _POSITIONS.index(after) + 1
        if index == len(_POSITIONS):
            return None

        async def handle(rows: int, files: int) -> RetentionUnitUsage:
            if rows < needs:
                # Like a File family: discovery is charged, the unit retries.
                return RetentionUnitUsage(
                    rows=1, files=0, disposition=RetentionUnitDisposition.DOES_NOT_FIT
                )
            out.add(None, "deleted")
            return RetentionUnitUsage(rows=needs, files=file_charge)

        return _POSITIONS[index], handle

    result = await gather_retention_units(
        next_candidate,
        out,
        max_rows=max_rows,
        max_files=max_files,
        cursor=None,
        chunk_rows=chunk_rows,
        gather_seconds=10,
        deadline=math.inf,
    )

    assert len(selected) == calls
    assert (result.rows, result.files) == (rows, file_charge * deleted)
    assert (result.exhausted, result.deferred) == (exhausted, deferred)
    assert result.cursor == (_POSITIONS[cursor] if cursor is not None else None)
    assert sum(effect.counts.get("deleted", 0) for effect in result.effects) == deleted


async def test_gathering_stops_at_the_execution_deadline() -> None:
    """Mutant: gathering stops only after its own window and ignores the
    execution's deadline, admitting units after it."""
    now = [0.0]
    out = RetentionEffects()

    async def next_candidate(
        after: RetentionKeyset | None,
    ) -> RetentionUnitCandidate | None:
        index = 0 if after is None else _POSITIONS.index(after) + 1
        if index == len(_POSITIONS):
            return None

        async def handle(rows: int, files: int) -> RetentionUnitUsage:
            now[0] += 1.0
            return RetentionUnitUsage(rows=1, files=0)

        return _POSITIONS[index], handle

    result = await gather_retention_units(
        next_candidate,
        out,
        max_rows=10,
        max_files=0,
        cursor=None,
        chunk_rows=10,
        gather_seconds=10,
        deadline=1.0,
        clock=lambda: now[0],
    )

    assert (result.rows, result.cursor, result.exhausted) == (1, _POSITIONS[0], False)
