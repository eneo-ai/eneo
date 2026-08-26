from typing_extensions import TypedDict

from eneo.main.logging import get_logger
from eneo.object_content.file_icon_backfill import FileIconBackfillState
from eneo.object_content.runtime import ObjectContentRuntime, object_content_runtime

logger = get_logger(__name__)


class ObjectContentReconciliationSummary(TypedDict):
    lifecycle_advanced: int
    inline_deleted: int
    content_processed: int
    moves_processed: int
    references_audited: int
    reference_drifts: int
    missing_objects: int
    object_cycle_completed: bool
    multipart_aborted: int
    orphan_objects_deleted: int


class FileIconBackfillSummary(TypedDict):
    state: str
    target_kind: str | None
    claimed_count: int
    completed_count: int
    cancelled_count: int
    failed_count: int
    detail: str | None


async def reconcile_object_content_task(
    runtime: ObjectContentRuntime = object_content_runtime,
) -> ObjectContentReconciliationSummary:
    result = await runtime.reconcile_once()
    return {
        "lifecycle_advanced": result.lifecycle_advanced,
        "inline_deleted": result.inline_deleted,
        "content_processed": result.content_processed,
        "moves_processed": result.moves_processed,
        "references_audited": result.references_audited,
        "reference_drifts": result.reference_drifts,
        "missing_objects": result.missing_objects,
        "object_cycle_completed": result.object_cycle_completed,
        "multipart_aborted": result.multipart_aborted,
        "orphan_objects_deleted": result.orphan_objects_deleted,
    }


async def backfill_file_icon_content_task(
    runtime: ObjectContentRuntime = object_content_runtime,
) -> FileIconBackfillSummary:
    result = await runtime.backfill_file_icons_once()
    summary: FileIconBackfillSummary = {
        "state": result.state.value,
        "target_kind": (
            None if result.target_kind is None else result.target_kind.value
        ),
        "claimed_count": result.claimed_count,
        "completed_count": result.completed_count,
        "cancelled_count": result.cancelled_count,
        "failed_count": result.failed_count,
        "detail": result.detail,
    }
    if result.claimed_count:
        logger.info("File/Icon legacy backfill progress", extra=summary)
    elif result.state in {
        FileIconBackfillState.WAITING_FOR_CAPACITY,
        FileIconBackfillState.WAITING_FOR_OBJECT_STORE,
        FileIconBackfillState.HALTED,
    }:
        logger.warning("File/Icon legacy backfill needs operator action", extra=summary)
    return summary
