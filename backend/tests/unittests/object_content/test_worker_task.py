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
        "claimed_count": 3,
        "completed_count": 2,
        "cancelled_count": 1,
        "failed_count": 0,
        "detail": None,
    }
    runtime.backfill_file_icons_once.assert_awaited_once_with()
