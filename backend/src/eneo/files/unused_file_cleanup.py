"""Delete uploaded Files that no product record uses anymore.

A File family is in use while a chat message, Assistant, App or App run links
to any of its members. Manual deletion calls ``delete_unused_root_files``;
retention uses the same reference owner within its bounded atomic unit. Both
release uploads when their last use is removed. The registered unused-files
task catches cascades from deleting an Assistant, App, Space or group chat,
uploads that were never attached, and Files left behind before this cleanup existed.

Every deletion locks the family and re-checks its usage first. Deleting the
Files row releases its content references, and the object-content lifecycle
removes the stored bytes, including audio originals and transcriptions.

Operators can preview or run one budgeted execution inside the worker environment:
    python -m eneo.files.unused_file_cleanup preview|run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.application.retention_sql_limits import set_retention_timeouts
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.files.file_usage import FileUsageRepository
from eneo.main.config import get_settings


@dataclass
class UnusedFileSweepResult:
    """Unused File families (a root with its derived Files) and their stored bytes."""

    dry_run: bool
    families: int = 0
    # Managed bytes of every family together, not per organization.
    managed_bytes: int = 0
    families_by_tenant: dict[str, int] = field(default_factory=dict[str, int])


async def delete_unused_root_files(
    session: AsyncSession,
    candidate_file_ids: Iterable[UUID],
) -> int:
    """Delete candidate root Files, with their derived Files, once unused."""
    unused_ids = await FileUsageRepository(session).lock_unused_root_families(
        candidate_file_ids
    )
    if not unused_ids:
        return 0
    result = await session.execute(sa.delete(Files).where(Files.id.in_(unused_ids)))
    return affected_row_count(result)


async def preview_unused_files(
    session: AsyncSession,
    *,
    older_than: timedelta,
    page_size: int,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> UnusedFileSweepResult:
    """Advisory inventory using the same reference owner as retention deletion.

    Each page locks its candidate families like a retention chunk, so it takes
    the chunk's wait limits: a File a user holds ends the preview with a lock
    timeout instead of making that user wait for it.
    """
    result = UnusedFileSweepResult(dry_run=True)
    tenants: Counter[str] = Counter()
    after: UUID | None = None
    while True:
        async with session.begin():
            await set_retention_timeouts(
                session,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
            )
            usage = FileUsageRepository(session)
            page = await usage.list_unreferenced_roots(
                after=after,
                older_than=older_than,
                limit=page_size,
            )
            if not page:
                break
            after = page[-1]
            unused_ids = await usage.lock_unused_root_families(page)
            if not unused_ids:
                continue
            tenants.update(await _tenant_counts(session, unused_ids))
            result.managed_bytes += await _managed_bytes(session, unused_ids)
            result.families += len(unused_ids)
    result.families_by_tenant = dict(sorted(tenants.items()))
    return result


async def _tenant_counts(session: AsyncSession, root_ids: list[UUID]) -> Counter[str]:
    rows = (
        await session.execute(
            sa.select(Files.tenant_id, sa.func.count())
            .where(Files.id.in_(root_ids))
            .group_by(Files.tenant_id)
        )
    ).all()
    return Counter({str(tenant_id): count for tenant_id, count in rows})


async def _managed_bytes(session: AsyncSession, root_ids: list[UUID]) -> int:
    family = (
        sa.select(Files.id)
        .where(Files.id.in_(root_ids))
        .cte("unused_file_family", recursive=True)
    )
    family = family.union_all(
        sa.select(Files.id).join(family, Files.parent_file_id == family.c.id)
    )
    total = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(ObjectContents.size_bytes), 0))
        .select_from(FileContentReferences)
        .join(ObjectContents, ObjectContents.id == FileContentReferences.content_id)
        .where(FileContentReferences.file_id.in_(sa.select(family.c.id)))
    )
    return int(total or 0)


async def _run_from_cli(*, dry_run: bool) -> UnusedFileSweepResult | RetentionRunReport:
    from dependency_injector import providers

    from eneo.data_retention.infrastructure.retention_worker import retention_runner
    from eneo.database.database import DatabaseSessionManager
    from eneo.files.unused_file_retention_task import UNUSED_FILES_TASK
    from eneo.main.container.container import Container
    from eneo.main.retention_tasks import retention_task_registrations

    settings = get_settings()
    database = DatabaseSessionManager()
    database.init(settings.database_url)
    try:
        async with database.session() as session:
            if dry_run:
                return await preview_unused_files(
                    session,
                    older_than=timedelta(
                        hours=settings.retention_unused_file_grace_hours
                    ),
                    page_size=settings.retention_chunk_rows,
                    statement_timeout_ms=settings.retention_chunk_statement_timeout_ms,
                    lock_timeout_ms=settings.retention_chunk_lock_timeout_ms,
                )
            registration = next(
                task
                for task in retention_task_registrations(settings)
                if task.name == UNUSED_FILES_TASK
            )
            runner = retention_runner(
                session=session,
                container=Container(session=providers.Object(session)),
                settings=settings,
                budget=registration.budget,
            )
            if not registration.enabled:
                return await runner.skip(registration.name)
            return await runner.run(registration.build(session))
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "run"))
    arguments = parser.parse_args()
    # App loggers bind their console stream on import. Keep diagnostics on
    # stderr and reserve stdout for one complete JSON result.
    with redirect_stdout(sys.stderr):
        result = asyncio.run(_run_from_cli(dry_run=arguments.command == "preview"))
    report_type: TypeAdapter[UnusedFileSweepResult | RetentionRunReport] = TypeAdapter(
        UnusedFileSweepResult | RetentionRunReport
    )
    print(report_type.dump_json(result, indent=2).decode())


if __name__ == "__main__":
    main()
