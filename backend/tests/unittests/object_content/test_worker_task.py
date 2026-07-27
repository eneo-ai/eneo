from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.object_content.reconciliation import ReconciliationResult
from eneo.object_content.runtime import ObjectContentRuntime
from eneo.worker.object_content_tasks import reconcile_object_content_task


@pytest.mark.asyncio
async def test_worker_task_returns_only_bounded_sanitized_counts() -> None:
    runtime = MagicMock(spec=ObjectContentRuntime)
    runtime.reconcile_once = AsyncMock(
        return_value=ReconciliationResult(
            lifecycle_advanced=1,
            inline_deleted=8,
            content_processed=2,
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
        "references_audited": 3,
        "reference_drifts": 4,
        "missing_objects": 5,
        "object_cycle_completed": True,
        "multipart_aborted": 6,
        "orphan_objects_deleted": 7,
    }
    runtime.reconcile_once.assert_awaited_once_with()
