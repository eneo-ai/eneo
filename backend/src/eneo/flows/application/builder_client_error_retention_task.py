"""The Builder failure ledger adopts the shared retention runner."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.flows.infrastructure.builder_client_error_retention_repo import (
    BuilderClientErrorRetentionRepository,
)

BUILDER_CLIENT_ERROR_TASK = "builder.client_errors"


class BuilderClientErrorRetentionTask:
    count_keys = frozenset({"client_errors_deleted"})
    blocked_keys = frozenset[str]()

    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.repository = BuilderClientErrorRetentionRepository(session, now=now)

    @property
    def name(self) -> str:
        return BUILDER_CLIENT_ERROR_TASK

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep("client_errors", self._delete, max_files=0),)

    async def _delete(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()
        limit = batch.rows // 2
        if limit == 0:
            return out.result(
                rows=0, exhausted=False, deferred=True, cursor=batch.cursor
            )
        roots = await self.repository.lock_due_page(batch.cursor, limit)
        if not roots:
            return out.result(rows=0, exhausted=True, cursor=batch.cursor)
        deleted = await self.repository.delete_due([root.id for root in roots])
        for _identifier, tenant_id in deleted:
            out.add(tenant_id, "client_errors_deleted")
        return out.result(
            rows=len(roots) + len(deleted),
            exhausted=len(roots) < limit,
            cursor=roots[-1],
        )
