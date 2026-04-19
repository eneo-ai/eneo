import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.data_retention.constants import ORPHANED_SESSION_CLEANUP_DAYS
from intric.database.tables.app_table import AppRuns, Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.flows.flow_retention_policy import resolve_flow_retention_policy

logger = logging.getLogger(__name__)

# Batch size for retention deletions to prevent transaction timeouts
RETENTION_BATCH_SIZE = 5000


class FlowRuntimeCleanupCounts(TypedDict):
    debug_step_results: int
    debug_step_attempts: int
    generated_artifact_rows: int
    generated_artifact_files: int
    reconciled_artifact_references: int


class DataRetentionService:
    """Service for managing data retention and deletion based on hierarchical policies."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session

    async def cleanup_old_flow_runtime_data(self) -> FlowRuntimeCleanupCounts:
        now = datetime.now(timezone.utc)
        counts: FlowRuntimeCleanupCounts = {
            "debug_step_results": 0,
            "debug_step_attempts": 0,
            "generated_artifact_rows": 0,
            "generated_artifact_files": 0,
            "reconciled_artifact_references": 0,
        }
        async for terminal_runs in self._iter_flow_run_retention_rows(
            older_than=now - timedelta(days=1)
        ):
            debug_run_ids: set[UUID] = set()
            artifact_run_ids: set[UUID] = set()

            for row in terminal_runs:
                anchor = row["retention_anchor"]
                if anchor is None:
                    continue
                policy = resolve_flow_retention_policy(row["flow_settings"])
                flow_override_days = row["flow_retention_days"]
                space_default_days = row["space_retention_days"]

                debug_retention_days = policy.retention_for_class(
                    "run_debug_evidence",
                    space_default_days=space_default_days,
                    flow_override_days=flow_override_days,
                )
                if debug_retention_days is not None and anchor <= now - timedelta(
                    days=debug_retention_days
                ):
                    debug_run_ids.add(row["run_id"])

                artifact_retention_days = policy.retention_for_class(
                    "generated_artifact",
                    space_default_days=space_default_days,
                    flow_override_days=flow_override_days,
                )
                if artifact_retention_days is not None and anchor <= now - timedelta(
                    days=artifact_retention_days
                ):
                    artifact_run_ids.add(row["run_id"])

            if debug_run_ids:
                debug_counts = await self._cleanup_old_flow_debug_evidence(
                    debug_run_ids
                )
                counts["debug_step_results"] += debug_counts["debug_step_results"]
                counts["debug_step_attempts"] += debug_counts["debug_step_attempts"]
            if artifact_run_ids:
                artifact_counts = await self._cleanup_old_generated_flow_artifacts(
                    artifact_run_ids
                )
                counts["generated_artifact_rows"] += artifact_counts[
                    "generated_artifact_rows"
                ]
                counts["generated_artifact_files"] += artifact_counts[
                    "generated_artifact_files"
                ]
        counts[
            "reconciled_artifact_references"
        ] = await self._reconcile_missing_generated_artifact_references()
        return counts

    def _build_effective_retention_days(
        self,
        entity_retention_col: Any,
        space_retention_col: Any = Spaces.data_retention_days,
    ) -> Any:
        """
        Build COALESCE expression for hierarchical retention policy.

        The hierarchy is:
        1. Entity-level retention (Assistant/App specific)
        2. Space-level retention
        3. Tenant-level retention (if enabled)
        4. NULL (keep forever)

        Args:
            entity_retention_col: Column for entity-level retention (e.g., Assistants.data_retention_days)
            space_retention_col: Column for space-level retention (default: Spaces.data_retention_days)

        Returns:
            SQLAlchemy COALESCE expression
        """
        return sa.func.coalesce(
            entity_retention_col,
            space_retention_col,
            sa.case(
                (
                    AuditRetentionPolicy.conversation_retention_enabled.is_(True),
                    AuditRetentionPolicy.conversation_retention_days,
                ),
                else_=None,
            ),
        )

    async def _delete_old_records(
        self,
        record_table: type,
        entity_table: type,
        entity_retention_col: Any,
        entity_fk_col: Any,
        record_fk_col: Any,
        record_type: str,
    ) -> int:
        """
        Generic method to delete old records based on hierarchical retention policies.

        Uses batch deletion to prevent transaction timeouts on large datasets.

        Args:
            record_table: Table to delete from (e.g., Questions, AppRuns)
            entity_table: Parent entity table (e.g., Assistants, Apps)
            entity_retention_col: Entity's retention days column
            entity_fk_col: Foreign key column in entity table to Space
            record_fk_col: Foreign key column in record table to entity
            record_type: Human-readable record type for logging

        Returns:
            Number of records deleted
        """
        logger.info(
            f"Starting deletion of old {record_type} based on retention policies"
        )

        # Build effective retention days using hierarchy
        effective_retention_days = self._build_effective_retention_days(
            entity_retention_col
        )

        # Build base subquery to identify records to delete (will be limited per batch)
        base_subquery = cast(
            sa.Select[Any],
            sa.select(record_table.id)  # type: ignore[attr-defined]
            .join(entity_table, record_fk_col == entity_table.id)  # type: ignore[attr-defined]
            .join(Spaces, entity_fk_col == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    record_table.created_at  # type: ignore[attr-defined]
                    # make_interval signature: (years, months, weeks, days, hours, mins, secs)
                    < sa.func.now()
                    - sa.func.make_interval(0, 0, 0, effective_retention_days),
                )
            ),
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # Delete batch of records (ORDER BY ensures deterministic batch selection)
            batch_subquery = base_subquery.order_by(record_table.id).limit(  # type: ignore[attr-defined]
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(record_table).where(record_table.id.in_(batch_subquery))  # type: ignore[attr-defined]
            result = await self.session.execute(query)
            batch_deleted = result.rowcount

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} {record_type} (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(
                f"Deleted {total_deleted} old {record_type} based on retention policies"
            )
        else:
            logger.debug(f"No old {record_type} to delete based on retention policies")

        return total_deleted

    async def delete_old_questions(self) -> int:
        """
        Delete old questions using hierarchical retention policy resolution:
        1. Assistant-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of questions deleted
        """
        return await self._delete_old_records(
            record_table=Questions,
            entity_table=Assistants,
            entity_retention_col=Assistants.data_retention_days,
            entity_fk_col=Assistants.space_id,
            record_fk_col=Questions.assistant_id,
            record_type="questions",
        )

    async def delete_old_app_runs(self) -> int:
        """
        Delete old app runs using hierarchical retention policy resolution:
        1. App-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of app runs deleted
        """
        return await self._delete_old_records(
            record_table=AppRuns,
            entity_table=Apps,
            entity_retention_col=Apps.data_retention_days,
            entity_fk_col=Apps.space_id,
            record_fk_col=AppRuns.app_id,
            record_type="app runs",
        )

    async def delete_old_sessions(self) -> int:
        """
        Delete orphaned sessions that have no questions.

        Sessions without questions are deleted after ORPHANED_SESSION_CLEANUP_DAYS.
        Uses batch deletion to prevent transaction timeouts on large datasets.

        Returns:
            Number of sessions deleted
        """
        logger.info(
            f"Starting deletion of orphaned sessions older than {ORPHANED_SESSION_CLEANUP_DAYS} day(s)"
        )

        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(
            0, 0, 0, ORPHANED_SESSION_CLEANUP_DAYS
        )

        # Build base subquery to identify orphaned sessions (will be limited per batch)
        base_subquery = (
            sa.select(Sessions.id)
            .outerjoin(Questions, Sessions.id == Questions.session_id)
            .where(sa.and_(Sessions.created_at < cutoff_expr, Questions.id.is_(None)))
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # ORDER BY ensures deterministic batch selection
            batch_subquery = base_subquery.order_by(Sessions.id).limit(
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(Sessions).where(Sessions.id.in_(batch_subquery))
            result = await self.session.execute(query)
            batch_deleted = result.rowcount

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} orphaned sessions (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(f"Deleted {total_deleted} orphaned sessions")
        else:
            logger.debug("No orphaned sessions to delete")

        return total_deleted

    async def get_affected_questions_count_for_assistant(
        self, assistant_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted for a specific assistant."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(Questions.id)).where(
            sa.and_(
                Questions.assistant_id == assistant_id,
                Questions.created_at < cutoff_expr,
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_app(
        self, app_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted for a specific app."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(AppRuns.id)).where(
            sa.and_(AppRuns.app_id == app_id, AppRuns.created_at < cutoff_expr)
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def _iter_flow_run_retention_rows(self, *, older_than: datetime):
        anchor = sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)
        last_run_id: UUID | None = None
        while True:
            stmt = (
                sa.select(
                    FlowRuns.id.label("run_id"),
                    anchor.label("retention_anchor"),
                    Flows.data_retention_days.label("flow_retention_days"),
                    Spaces.data_retention_days.label("space_retention_days"),
                    Tenants.flow_settings.label("flow_settings"),
                )
                .join(Flows, FlowRuns.flow_id == Flows.id)
                .join(Spaces, Flows.space_id == Spaces.id)
                .join(Tenants, FlowRuns.tenant_id == Tenants.id)
                .where(
                    sa.and_(
                        FlowRuns.status.in_(("completed", "failed", "cancelled")),
                        anchor < older_than,
                        FlowRuns.id > last_run_id
                        if last_run_id is not None
                        else sa.true(),
                    )
                )
                .order_by(FlowRuns.id)
                .limit(RETENTION_BATCH_SIZE)
            )
            result = await self.session.execute(stmt)
            rows = [dict(row) for row in result.mappings().all()]
            if not rows:
                break
            last_run_id = cast(UUID, rows[-1]["run_id"])
            yield rows

    async def _cleanup_old_flow_debug_evidence(
        self, run_ids: set[UUID]
    ) -> FlowRuntimeCleanupCounts:
        if not run_ids:
            return {
                "debug_step_results": 0,
                "debug_step_attempts": 0,
                "generated_artifact_rows": 0,
                "generated_artifact_files": 0,
                "reconciled_artifact_references": 0,
            }

        step_result_stmt = sa.select(
            FlowStepResults.id,
            FlowStepResults.input_payload_json,
            FlowStepResults.effective_prompt,
            FlowStepResults.output_payload_json,
            FlowStepResults.model_parameters_json,
            FlowStepResults.tool_calls_metadata,
        ).where(FlowStepResults.flow_run_id.in_(run_ids))
        step_result_rows = await self.session.execute(step_result_stmt)
        debug_step_results = 0
        for row in step_result_rows.fetchall():
            pruned_output = _prune_debug_payload(row.output_payload_json)
            needs_update = (
                any(
                    value is not None
                    for value in (
                        row.input_payload_json,
                        row.effective_prompt,
                        row.model_parameters_json,
                        row.tool_calls_metadata,
                    )
                )
                or pruned_output != row.output_payload_json
            )
            if not needs_update:
                continue
            result = await self.session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == row.id)
                .values(
                    input_payload_json=None,
                    effective_prompt=None,
                    output_payload_json=pruned_output,
                    model_parameters_json=None,
                    tool_calls_metadata=None,
                )
            )
            debug_step_results += result.rowcount or 0

        attempt_stmt = (
            sa.update(FlowStepAttempts)
            .where(
                sa.and_(
                    FlowStepAttempts.flow_run_id.in_(run_ids),
                    FlowStepAttempts.provenance_json.is_not(None),
                )
            )
            .values(provenance_json=None)
        )
        attempt_result = await self.session.execute(attempt_stmt)

        return {
            "debug_step_results": debug_step_results,
            "debug_step_attempts": attempt_result.rowcount or 0,
            "generated_artifact_rows": 0,
            "generated_artifact_files": 0,
            "reconciled_artifact_references": 0,
        }

    async def _cleanup_old_generated_flow_artifacts(
        self, run_ids: set[UUID]
    ) -> FlowRuntimeCleanupCounts:
        if not run_ids:
            return {
                "debug_step_results": 0,
                "debug_step_attempts": 0,
                "generated_artifact_rows": 0,
                "generated_artifact_files": 0,
                "reconciled_artifact_references": 0,
            }

        stmt = sa.select(
            FlowStepResults.id,
            FlowStepResults.tenant_id,
            FlowStepResults.output_payload_json,
        ).where(
            sa.and_(
                FlowStepResults.flow_run_id.in_(run_ids),
                FlowStepResults.output_payload_json.is_not(None),
            )
        )
        rows = await self.session.execute(stmt)
        file_ids_by_tenant: dict[UUID, set[UUID]] = defaultdict(set)
        updated_rows = 0

        for row in rows.fetchall():
            file_ids = _extract_generated_file_ids(row.output_payload_json)
            if not file_ids:
                continue
            pruned_payload = _prune_generated_artifact_payload(row.output_payload_json)
            update_result = await self.session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == row.id)
                .values(output_payload_json=pruned_payload)
            )
            updated_rows += update_result.rowcount or 0
            file_ids_by_tenant[row.tenant_id].update(file_ids)

        cleared_files = 0
        for tenant_id, file_ids in file_ids_by_tenant.items():
            clear_stmt = (
                sa.update(Files)
                .where(
                    sa.and_(
                        Files.tenant_id == tenant_id,
                        Files.id.in_(file_ids),
                        sa.or_(
                            Files.blob.is_not(None),
                            Files.text.is_not(None),
                            Files.transcription.is_not(None),
                        ),
                    )
                )
                .values(blob=None, text=None, transcription=None)
            )
            clear_result = await self.session.execute(clear_stmt)
            cleared_files += clear_result.rowcount or 0

        return {
            "debug_step_results": 0,
            "debug_step_attempts": 0,
            "generated_artifact_rows": updated_rows,
            "generated_artifact_files": cleared_files,
            "reconciled_artifact_references": 0,
        }

    async def _reconcile_missing_generated_artifact_references(self) -> int:
        reconciled = 0
        last_step_result_id: UUID | None = None
        while True:
            stmt = (
                sa.select(
                    FlowStepResults.id,
                    FlowStepResults.output_payload_json,
                )
                .where(
                    sa.and_(
                        FlowStepResults.output_payload_json.is_not(None),
                        (
                            FlowStepResults.id > last_step_result_id
                            if last_step_result_id is not None
                            else sa.true()
                        ),
                    )
                )
                .order_by(FlowStepResults.id)
                .limit(RETENTION_BATCH_SIZE)
            )
            rows = await self.session.execute(stmt)
            batch_rows = rows.fetchall()
            if not batch_rows:
                break

            payloads_by_row: dict[UUID, dict[str, Any]] = {}
            referenced_file_ids: set[UUID] = set()
            for row in batch_rows:
                payload = row.output_payload_json
                if not isinstance(payload, dict):
                    continue
                file_ids = _extract_generated_file_ids(payload)
                if not file_ids:
                    continue
                payloads_by_row[row.id] = payload
                referenced_file_ids.update(file_ids)

            if referenced_file_ids:
                file_rows = await self.session.execute(
                    sa.select(Files.id, Files.blob, Files.text).where(
                        Files.id.in_(referenced_file_ids)
                    )
                )
                file_state = {
                    row.id: (row.blob is not None or row.text is not None)
                    for row in file_rows.fetchall()
                }

                for row_id, payload in payloads_by_row.items():
                    missing_ids = {
                        file_id
                        for file_id in _extract_generated_file_ids(payload)
                        if not file_state.get(file_id, False)
                    }
                    if not missing_ids:
                        continue
                    pruned_payload = _prune_generated_artifact_payload(
                        payload,
                        only_file_ids=missing_ids,
                    )
                    result = await self.session.execute(
                        sa.update(FlowStepResults)
                        .where(FlowStepResults.id == row_id)
                        .values(output_payload_json=pruned_payload)
                    )
                    reconciled += result.rowcount or 0

            last_step_result_id = cast(UUID, batch_rows[-1].id)

        return reconciled

    async def get_affected_questions_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted across all assistants in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .where(
                sa.and_(
                    Assistants.space_id == space_id,
                    Questions.created_at < cutoff_expr,
                    # Only count questions that don't have assistant-level retention
                    # (those would use their own retention policy)
                    Assistants.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted across all apps in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .where(
                sa.and_(
                    Apps.space_id == space_id,
                    AppRuns.created_at < cutoff_expr,
                    # Only count app runs that don't have app-level retention
                    Apps.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_total_count_for_tenant(
        self, tenant_id: UUID, retention_days: int
    ) -> dict[str, int]:
        """Get count of questions and app runs that would be deleted tenant-wide."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        # Count questions without assistant or space level retention
        questions_query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .join(Spaces, Assistants.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    Questions.created_at < cutoff_expr,
                    Assistants.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        # Count app runs without app or space level retention
        app_runs_query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .join(Spaces, Apps.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    AppRuns.created_at < cutoff_expr,
                    Apps.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        questions_result = await self.session.execute(questions_query)
        app_runs_result = await self.session.execute(app_runs_query)

        questions_count = questions_result.scalar() or 0
        app_runs_count = app_runs_result.scalar() or 0

        return {
            "questions": questions_count,
            "app_runs": app_runs_count,
            "total": questions_count + app_runs_count,
        }


def _prune_debug_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload_dict = cast(dict[str, Any], payload)
    pruned: dict[str, Any] = dict(payload_dict)
    pruned.pop("template_fill_debug", None)
    return pruned


def _extract_generated_file_ids(payload: Any) -> set[UUID]:
    if not isinstance(payload, dict):
        return set()
    payload_dict = cast(dict[str, Any], payload)
    file_ids: set[UUID] = set()
    for raw_file_id in cast(list[Any], payload_dict.get("generated_file_ids", [])):
        try:
            file_ids.add(UUID(str(raw_file_id)))
        except (TypeError, ValueError):
            continue
    for raw_file_id in cast(list[Any], payload_dict.get("file_ids", [])):
        try:
            file_ids.add(UUID(str(raw_file_id)))
        except (TypeError, ValueError):
            continue
    for artifact in cast(list[Any], payload_dict.get("artifacts", [])):
        if not isinstance(artifact, dict):
            continue
        artifact_dict = cast(dict[str, Any], artifact)
        raw_file_id = artifact_dict.get("file_id")
        if raw_file_id is None:
            continue
        try:
            file_ids.add(UUID(str(raw_file_id)))
        except (TypeError, ValueError):
            continue
    return file_ids


def _prune_generated_artifact_payload(
    payload: Any,
    *,
    only_file_ids: set[UUID] | None = None,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload_dict = cast(dict[str, Any], payload)

    def should_remove(raw_file_id: Any) -> bool:
        try:
            file_id = UUID(str(raw_file_id))
        except (TypeError, ValueError):
            return False
        return only_file_ids is None or file_id in only_file_ids

    pruned: dict[str, Any] = dict(payload_dict)
    artifacts = pruned.get("artifacts")
    if isinstance(artifacts, list):
        next_artifacts: list[Any] = []
        for raw_artifact in cast(list[Any], artifacts):
            if isinstance(raw_artifact, dict) and should_remove(
                cast(dict[str, Any], raw_artifact).get("file_id")
            ):
                continue
            next_artifacts.append(raw_artifact)
        if next_artifacts:
            pruned["artifacts"] = next_artifacts
        else:
            pruned.pop("artifacts", None)

    for key in ("generated_file_ids", "file_ids"):
        raw_ids = pruned.get(key)
        if not isinstance(raw_ids, list):
            continue
        next_ids: list[Any] = []
        for raw_file_id in cast(list[Any], raw_ids):
            if should_remove(raw_file_id):
                continue
            next_ids.append(raw_file_id)
        if next_ids:
            pruned[key] = next_ids
        else:
            pruned.pop(key, None)

    return pruned
