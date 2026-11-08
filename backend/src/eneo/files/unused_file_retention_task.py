"""Unused uploads adopt the same bounded execution as conversation retention."""

from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.files.file_retention import FileRetentionReason
from eneo.files.file_usage import FileUsageRepository

UNUSED_FILES_TASK = "files.unused"


class UnusedFileRetentionTask:
    name = UNUSED_FILES_TASK
    count_keys = frozenset(
        {"roots_deleted", "files_deleted", "file_dependencies_deleted"}
    )
    # A root kept in its own state (in use, gone, a derived File) is progress,
    # not audit; a refused root is blocked.
    observation_keys = frozenset(
        reason.key
        for reason in FileRetentionReason
        if not reason.is_refusal and reason is not FileRetentionReason.DELETED
    )
    blocked_keys = frozenset(
        reason.key for reason in FileRetentionReason if reason.is_refusal
    )

    def __init__(
        self,
        session: AsyncSession,
        *,
        grace: timedelta,
        family_rows: int,
        execution_files: int,
        chunk_rows: int,
        gather_seconds: float,
    ) -> None:
        self.session = session
        self.repository = FileUsageRepository(session)
        self.grace = grace
        self.family_rows = family_rows
        self.execution_files = execution_files
        self.chunk_rows = chunk_rows
        self.gather_seconds = gather_seconds

    def steps(self) -> Sequence[RetentionStep]:
        return (
            RetentionStep(
                "families",
                self._families,
                max_batch=max(self.chunk_rows, self.family_rows + 1),
                max_files=self.execution_files,
            ),
        )

    async def _families(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()

        async def next_candidate(
            cursor: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            root = await self.repository.next_retention_root(
                after=(cursor.at, cursor.id) if cursor is not None else None,
                older_than=self.grace,
            )
            if root is None:
                return None
            at, file_id, in_use = root

            async def kept(rows: int, files: int) -> RetentionUnitUsage:
                # Its own use is visible without a lock: charge its discovery.
                out.add(None, FileRetentionReason.IN_USE.key)
                return RetentionUnitUsage(rows=1, files=0)

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                async with self.session.begin_nested() as unit:
                    result = await self.repository.delete_unused_root(
                        file_id,
                        max_rows=rows - 1,
                        max_files=files,
                        max_family_rows=self.family_rows,
                        older_than=self.grace,
                    )
                    if result.needs_rollback:
                        await unit.rollback()
                disposition = RetentionUnitDisposition.DONE
                if result.reason is FileRetentionReason.INSUFFICIENT_BUDGET and (
                    rows < self.family_rows + 1 or files < self.execution_files
                ):
                    # Short of a fully funded unit: retried in a fresh chunk.
                    disposition = RetentionUnitDisposition.DOES_NOT_FIT
                elif result.reason.is_refusal:
                    out.blocked[result.reason.key] += 1
                elif result.reason is not FileRetentionReason.DELETED:
                    # Includes a use attached after the root was read, or one
                    # of a derived File.
                    out.add(None, result.reason.key)
                out.add(result.tenant_id, "roots_deleted", result.deleted_roots)
                out.add(result.tenant_id, "files_deleted", result.deleted_members)
                out.add(
                    result.tenant_id,
                    "file_dependencies_deleted",
                    result.deleted_references,
                )
                return RetentionUnitUsage(
                    rows=1 + result.rows, files=result.files, disposition=disposition
                )

            return RetentionKeyset(at=at, id=file_id), kept if in_use else handle

        return await gather_retention_units(
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=self.chunk_rows,
            gather_seconds=self.gather_seconds,
            deadline=batch.deadline,
        )
