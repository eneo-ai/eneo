from typing_extensions import TypedDict

from eneo.object_content.runtime import ObjectContentRuntime, object_content_runtime


class ObjectContentReconciliationSummary(TypedDict):
    lifecycle_advanced: int
    content_processed: int
    references_audited: int
    reference_drifts: int
    missing_objects: int
    object_cycle_completed: bool
    multipart_aborted: int
    orphan_objects_deleted: int


async def reconcile_object_content_task(
    runtime: ObjectContentRuntime = object_content_runtime,
) -> ObjectContentReconciliationSummary:
    result = await runtime.reconciler.run_once()
    return {
        "lifecycle_advanced": result.lifecycle_advanced,
        "content_processed": result.content_processed,
        "references_audited": result.references_audited,
        "reference_drifts": result.reference_drifts,
        "missing_objects": result.missing_objects,
        "object_cycle_completed": result.object_cycle_completed,
        "multipart_aborted": result.multipart_aborted,
        "orphan_objects_deleted": result.orphan_objects_deleted,
    }
