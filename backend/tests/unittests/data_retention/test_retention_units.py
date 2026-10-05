from datetime import datetime, timezone
from uuid import UUID

import pytest

from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionKeyset

_POSITION = RetentionKeyset(
    at=datetime(2026, 1, 1, tzinfo=timezone.utc), id=UUID(int=1)
)


@pytest.mark.parametrize(
    "max_rows,max_files,chunk_rows,file_charge,calls,rows,exhausted,deferred",
    [
        pytest.param(1, 0, 4, 0, 0, 0, False, True, id="fresh-minimum"),
        pytest.param(8, 0, 3, 0, 1, 2, False, False, id="remainder-minimum"),
        pytest.param(2, 0, 4, 0, 1, 2, False, False, id="exact-fit"),
        pytest.param(4, 0, 4, 0, 2, 2, True, False, id="row-only"),
        pytest.param(4, 1, 4, 1, 1, 2, False, False, id="file-budget"),
    ],
)
async def test_discovery_reserves_its_rows_before_selecting_a_candidate(
    max_rows: int,
    max_files: int,
    chunk_rows: int,
    file_charge: int,
    calls: int,
    rows: int,
    exhausted: bool,
    deferred: bool,
) -> None:
    """Kills M99 discovery before admission, M100 fresh routing and M101 row-only stop."""
    selected: list[RetentionKeyset | None] = []
    out = RetentionEffects()

    async def next_candidate(
        after: RetentionKeyset | None,
    ) -> RetentionUnitCandidate | None:
        selected.append(after)
        if after == _POSITION:
            return None

        async def handle(rows: int, files: int) -> RetentionUnitUsage:
            assert rows >= 2
            assert files >= file_charge
            out.add(None, "deleted")
            return RetentionUnitUsage(rows=2, files=file_charge)

        return _POSITION, handle

    result = await gather_retention_units(
        next_candidate,
        out,
        max_rows=max_rows,
        max_files=max_files,
        cursor=None,
        chunk_rows=chunk_rows,
        gather_seconds=10,
        min_candidate_rows=2,
    )

    assert len(selected) == calls
    assert (result.rows, result.files) == (rows, file_charge if rows else 0)
    assert (result.exhausted, result.deferred) == (exhausted, deferred)
    assert result.cursor == (_POSITION if rows else None)
    assert sum(effect.counts.get("deleted", 0) for effect in result.effects) == bool(
        rows
    )
