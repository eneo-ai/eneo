import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.object_content.content import StorageKind
from eneo.object_content.file_icon_backfill import (
    FileIconBackfillResult,
    FileIconBackfillState,
)
from eneo.object_content.reconciliation import ReconciliationResult
from eneo.object_content.runtime import ObjectContentRuntime
from eneo.worker import object_content_tasks
from eneo.worker.object_content_tasks import (
    backfill_file_icon_content_task,
    reconcile_object_content_task,
)


@pytest.mark.asyncio
async def test_worker_task_returns_only_bounded_sanitized_counts() -> None:
    runtime = MagicMock(spec=ObjectContentRuntime)
    runtime.reconcile_once = AsyncMock(
        return_value=ReconciliationResult(
            lifecycle_advanced=1,
            inline_deleted=8,
            content_processed=2,
            moves_processed=8,
            references_audited=3,
            reference_drifts=4,
            missing_objects=5,
            object_cycle_completed=True,
            multipart_aborted=6,
            orphan_objects_deleted=7,
        )
    )

    summary = await reconcile_object_content_task(cast(ObjectContentRuntime, runtime))

    assert summary == {
        "lifecycle_advanced": 1,
        "inline_deleted": 8,
        "content_processed": 2,
        "moves_processed": 8,
        "references_audited": 3,
        "reference_drifts": 4,
        "missing_objects": 5,
        "object_cycle_completed": True,
        "multipart_aborted": 6,
        "orphan_objects_deleted": 7,
    }
    runtime.reconcile_once.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_file_icon_backfill_task_returns_sanitized_progress() -> None:
    runtime = MagicMock(spec=ObjectContentRuntime)
    runtime.backfill_file_icons_once = AsyncMock(
        return_value=FileIconBackfillResult(
            state=FileIconBackfillState.ACTIVE,
            target_kind=StorageKind.POSTGRES_INLINE,
            admitted_count=4,
            claimed_count=3,
            completed_count=2,
            cancelled_count=1,
            failed_count=0,
            detail=None,
        )
    )

    summary = await backfill_file_icon_content_task(cast(ObjectContentRuntime, runtime))

    assert summary == {
        "state": "active",
        "target_kind": "postgres_inline",
        "admitted_count": 4,
        "claimed_count": 3,
        "completed_count": 2,
        "cancelled_count": 1,
        "failed_count": 0,
        "detail": None,
    }
    runtime.backfill_file_icons_once.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "detail", "admitted_count", "expected_level"),
    [
        (FileIconBackfillState.ACTIVE, "Waiting for a lease", 0, logging.INFO),
        (
            FileIconBackfillState.WAITING_FOR_CAPACITY,
            "Capacity acknowledgement required",
            4,
            logging.WARNING,
        ),
        (
            FileIconBackfillState.HALTED,
            "Operator action required",
            0,
            logging.WARNING,
        ),
        (FileIconBackfillState.COMPLETE, None, 0, None),
    ],
)
async def test_file_icon_backfill_task_logs_operational_state(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    state: FileIconBackfillState,
    detail: str | None,
    admitted_count: int,
    expected_level: int | None,
) -> None:
    logger = logging.getLogger(f"test_file_icon_backfill_task_{state.value}")
    logger.handlers = []
    monkeypatch.setattr(object_content_tasks, "logger", logger)
    runtime = MagicMock(spec=ObjectContentRuntime)
    runtime.backfill_file_icons_once = AsyncMock(
        return_value=FileIconBackfillResult(
            state=state,
            target_kind=StorageKind.POSTGRES_INLINE,
            admitted_count=admitted_count,
            claimed_count=0,
            completed_count=0,
            cancelled_count=0,
            failed_count=0,
            detail=detail,
        )
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        await backfill_file_icon_content_task(cast(ObjectContentRuntime, runtime))

    records = [record for record in caplog.records if record.name == logger.name]
    if expected_level is None:
        assert records == []
    else:
        assert len(records) == 1
        assert records[0].levelno == expected_level
        assert records[0].state == state.value
        assert records[0].admitted_count == admitted_count
        assert records[0].claimed_count == 0
