"""Shared skeleton for the per-model-type lifecycle cleanup workers.

When a model is soft-deleted (``deleted_at`` set) or migrated away from
(``migrated_to_model_id`` set), the row is kept as a tombstone so migration
history and lingering references still resolve. Once nothing references it
anymore the row serves no purpose and can be hard-deleted.

Completion has its own bespoke worker
(``completion_models.infrastructure.model_cleanup_worker``) because it also
reconciles soft-deleted *template* snapshots and is gated on historical
``questions`` rows. Transcription and embedding have simpler reference graphs
and share this skeleton: fetch lifecycle-ended candidates, then hard-delete each
in its own transaction once a final blocking-reference check passes. The
RESTRICT/SET NULL FKs are the database-level safety net — even if a check has a
bug, a RESTRICT FK refuses the delete and that single row is skipped.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Per-run batch cap. Keeps a single weekly invocation bounded even if the table
# somehow accumulates thousands of tombstones — the next run picks up the rest.
BATCH_LIMIT = 500

logger = logging.getLogger(__name__)

# (id, name) of a hard-delete candidate.
Candidate = tuple[UUID, str]


async def run_model_lifecycle_cleanup(
    *,
    session: AsyncSession,
    table: Any,
    find_candidates: Callable[[AsyncSession, int], Awaitable[list[Candidate]]],
    has_blocking_refs: Callable[[AsyncSession, UUID], Awaitable[bool]],
    job_label: str,
) -> dict[str, Any]:
    """Run one cleanup pass and return a structured result.

    ``find_candidates`` returns rows whose lifecycle has ended and that have no
    *structural* blockers (e.g. another model still pointing at them). Each
    candidate is then re-checked with ``has_blocking_refs`` inside its own
    transaction — a single failed delete must roll back only that row, not the
    whole run.
    """
    start_time = datetime.now(timezone.utc)
    results: dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "removed_models": [],
        "skipped_models": [],
        "errors": [],
        "success": True,
    }

    logger.info(f"Starting weekly {job_label} lifecycle cleanup job")

    async with session.begin():
        candidates = await find_candidates(session, BATCH_LIMIT)

    if not candidates:
        logger.info(f"No orphaned {job_label} tombstones to clean up")
        end_time = datetime.now(timezone.utc)
        results["end_time"] = end_time.isoformat()
        results["duration_seconds"] = (end_time - start_time).total_seconds()
        return results

    logger.info(f"Found {len(candidates)} candidate {job_label}s for cleanup")

    for model_id, model_name in candidates:
        try:
            async with session.begin():
                if await has_blocking_refs(session, model_id):
                    logger.info(
                        f"Skipping {job_label} '{model_name}' ({model_id}): "
                        f"still has active references"
                    )
                    results["skipped_models"].append(
                        {
                            "id": str(model_id),
                            "name": model_name,
                            "reason": "active_references",
                        }
                    )
                    continue

                # Hard-delete — RESTRICT FKs are the final safety net.
                await session.execute(sa.delete(table).where(table.id == model_id))

                logger.info(f"Removed orphaned {job_label} '{model_name}' ({model_id})")
                results["removed_models"].append(
                    {"id": str(model_id), "name": model_name}
                )
        except IntegrityError as e:
            logger.warning(
                f"Skipping {job_label} cleanup due to database restriction",
                extra={
                    "model_id": str(model_id),
                    "model_name": model_name,
                    "error": str(e),
                },
            )
            results["skipped_models"].append(
                {"id": str(model_id), "name": model_name, "reason": "db_restrict"}
            )
        except Exception as e:  # noqa: BLE001 — record and continue the batch
            error_msg = (
                f"Failed to remove {job_label} '{model_name}' ({model_id}): {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)
            results["success"] = False

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration

    removed = len(results["removed_models"])
    skipped = len(results["skipped_models"])
    errors = len(results["errors"])
    if results["success"]:
        logger.info(
            f"{job_label} cleanup completed: removed {removed}, "
            f"skipped {skipped}, duration {duration:.2f}s"
        )
    else:
        logger.warning(
            f"{job_label} cleanup completed with errors: removed {removed}, "
            f"skipped {skipped}, errors {errors}, duration {duration:.2f}s"
        )

    return results
