"""
Weekly lifecycle cleanup of orphaned completion models.

When a completion model is soft-deleted (deleted_at set) or migrated away from
(migrated_to_model_id set), it is kept in the database so that historical
question references and token usage analytics remain intact.

Once ALL references are gone — questions gallrad, active entities migrated,
no other model pointing to it via migrated_to_model_id — the row serves no
purpose and can be hard-deleted to keep the table clean.

This worker runs weekly and removes only models that satisfy ALL of:
  1. Marked by lifecycle state (deleted_at IS NOT NULL OR migrated_to_model_id IS NOT NULL)
  2. Zero questions referencing it
  3. Zero active entity references (assistants, apps, services, spaces, non-deleted templates)
  4. No other model has migrated_to_model_id pointing to it

The RESTRICT FK on questions.completion_model_id acts as a final safety net:
even if the checks above have a bug, the database will refuse the delete.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.exc import IntegrityError

from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.database.database import sessionmanager
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.questions_table import Questions
from intric.main.container.container import Container
from intric.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()


async def _find_removable_models(session) -> list[dict]:
    """
    Return completion models whose lifecycle has ended and which have no
    remaining historical or active references.

    A model is removable when:
      - deleted_at IS NOT NULL OR migrated_to_model_id IS NOT NULL
      - no questions reference it
      - no other model references it via migrated_to_model_id
    """
    # Subquery: count questions per model
    questions_count = (
        sa.select(
            Questions.completion_model_id,
            sa.func.count().label("cnt"),
        )
        .group_by(Questions.completion_model_id)
        .subquery()
    )

    # Subquery: count models that have migrated_to_model_id pointing here
    migration_refs = (
        sa.select(
            CompletionModels.migrated_to_model_id.label("target_id"),
            sa.func.count().label("cnt"),
        )
        .where(CompletionModels.migrated_to_model_id.isnot(None))
        .group_by(CompletionModels.migrated_to_model_id)
        .subquery()
    )

    stmt = (
        sa.select(
            CompletionModels.id,
            CompletionModels.name,
            CompletionModels.deleted_at,
            CompletionModels.migrated_to_model_id,
        )
        .outerjoin(questions_count, CompletionModels.id == questions_count.c.completion_model_id)
        .outerjoin(migration_refs, CompletionModels.id == migration_refs.c.target_id)
        .where(
            sa.or_(
                CompletionModels.deleted_at.isnot(None),
                CompletionModels.migrated_to_model_id.isnot(None),
            ),
            sa.func.coalesce(questions_count.c.cnt, 0) == 0,
            sa.func.coalesce(migration_refs.c.cnt, 0) == 0,
        )
    )

    result = await session.execute(stmt)
    return [
        {
            "id": row.id,
            "name": row.name,
            "deleted_at": row.deleted_at,
            "migrated_to_model_id": row.migrated_to_model_id,
        }
        for row in result.all()
    ]


async def _has_active_entity_references(session, model_id) -> bool:
    """Check if any active configuration entities still reference this model."""
    repo = CompletionModelsRepository(session=session)
    return await repo.has_active_references(model_id)


async def _reconcile_deleted_template_references(
    session,
    model_id,
    replacement_model_id,
) -> None:
    """
    Remove stale references from soft-deleted templates before hard-delete.

    Deleted templates are not historical records, so they should not keep an old
    completion model alive forever. If the model was migrated, restore snapshots
    are updated to the replacement model; otherwise they are cleared to None.
    """
    from intric.database.tables.app_template_table import AppTemplates
    from intric.database.tables.assistant_template_table import AssistantTemplates

    replacement_value = str(replacement_model_id) if replacement_model_id else None

    for table in (AssistantTemplates, AppTemplates):
        stmt = (
            sa.select(table)
            .where(
                table.completion_model_id == model_id,
                table.deleted_at.isnot(None),
            )
        )
        result = await session.execute(stmt)
        templates = result.scalars().all()

        for template in templates:
            template.completion_model_id = replacement_model_id
            if template.original_snapshot is not None:
                template.original_snapshot = {
                    **template.original_snapshot,
                    "completion_model_id": replacement_value,
                }


@worker.cron_job(hour=4, minute=0, weekday={6})  # Sunday 4 AM
async def cleanup_orphaned_models(container: Container) -> Dict[str, Any]:
    """
    Weekly lifecycle cleanup: hard-delete completion models that no longer
    have any historical or active references.

    Models become eligible when they are either soft-deleted or marked as
    migrated away from. Questions remain historical blockers until retention
    removes them.
    """
    start_time = datetime.now(timezone.utc)

    results: Dict[str, Any] = {
        "start_time": start_time.isoformat(),
        "removed_models": [],
        "skipped_models": [],
        "errors": [],
        "success": True,
    }

    logger.info("Starting weekly model lifecycle cleanup job")

    async with sessionmanager.session() as session:
        container.session.override(providers.Object(session))
        try:
            # Step 1: Find lifecycle candidates (no questions, no incoming migration refs)
            async with session.begin():
                candidates = await _find_removable_models(session)

            if not candidates:
                logger.info("No orphaned lifecycle models to clean up")
                end_time = datetime.now(timezone.utc)
                results["end_time"] = end_time.isoformat()
                results["duration_seconds"] = (end_time - start_time).total_seconds()
                return results

            logger.info(f"Found {len(candidates)} candidate models for cleanup")

            # Step 2: Verify and delete each model individually
            for model_info in candidates:
                model_id = model_info["id"]
                model_name = model_info["name"]

                try:
                    async with session.begin():
                        # Double-check active entity references
                        if await _has_active_entity_references(session, model_id):
                            logger.info(
                                f"Skipping model '{model_name}' ({model_id}): "
                                f"still has active entity references"
                            )
                            results["skipped_models"].append(
                                {"id": str(model_id), "name": model_name, "reason": "active_references"}
                            )
                            continue

                        await _reconcile_deleted_template_references(
                            session,
                            model_id,
                            model_info["migrated_to_model_id"],
                        )

                        # Hard-delete — RESTRICT FKs are the final safety net
                        stmt = sa.delete(CompletionModels).where(CompletionModels.id == model_id)
                        await session.execute(stmt)

                        logger.info(f"Removed orphaned model '{model_name}' ({model_id})")
                        results["removed_models"].append(
                            {"id": str(model_id), "name": model_name}
                        )

                except IntegrityError as e:
                    logger.warning(
                        "Skipping lifecycle cleanup for model due to database restriction",
                        extra={
                            "model_id": str(model_id),
                            "model_name": model_name,
                            "error": str(e),
                        },
                    )
                    results["skipped_models"].append(
                        {"id": str(model_id), "name": model_name, "reason": "db_restrict"}
                    )
                except Exception as e:
                    error_msg = f"Failed to remove model '{model_name}' ({model_id}): {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    results["errors"].append(error_msg)
                    results["success"] = False

        finally:
            container.session.reset_override()

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration

    removed_count = len(results["removed_models"])
    skipped_count = len(results["skipped_models"])
    error_count = len(results["errors"])

    if results["success"]:
        logger.info(
            f"Model cleanup completed: removed {removed_count}, "
            f"skipped {skipped_count}, duration {duration:.2f}s"
        )
    else:
        logger.warning(
            f"Model cleanup completed with errors: removed {removed_count}, "
            f"skipped {skipped_count}, errors {error_count}, duration {duration:.2f}s"
        )

    return results
