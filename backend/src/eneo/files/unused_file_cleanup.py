"""Delete uploaded Files that no product record uses anymore.

A File family is in use while a chat message, Assistant, App or App run links
to any of its members. Deleting such a record calls
``delete_unused_root_files`` with the Files it used, so retention and manual
deletion release uploads immediately. The daily sweep catches everything
else: cascades from deleting an Assistant, App, Space or group chat, uploads
that were never attached, and Files left behind before this cleanup existed.

Every deletion locks the family and re-checks its usage first. Deleting the
Files row releases its content references, and the object-content lifecycle
removes the stored bytes, including audio originals and transcriptions.

Operators can preview or run the sweep inside the worker environment:
    python -m eneo.files.unused_file_cleanup preview|run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterable
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.files.file_usage import FileUsageRepository

# Uploads are linked to their chat message or App run in a later request, and
# generated images when the answer is saved. Younger unreferenced Files are
# left for the next sweep.
UNUSED_FILE_MIN_AGE = timedelta(hours=24)
UNUSED_FILE_SWEEP_PAGE_SIZE = 1000


@dataclass
class UnusedFileSweepResult:
    dry_run: bool
    files: int = 0
    managed_bytes: int = 0
    files_by_tenant: dict[str, int] = field(default_factory=dict[str, int])


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


async def sweep_unused_files(
    session: AsyncSession,
    *,
    dry_run: bool,
    older_than: timedelta = UNUSED_FILE_MIN_AGE,
    page_size: int = UNUSED_FILE_SWEEP_PAGE_SIZE,
) -> UnusedFileSweepResult:
    """Delete, or with ``dry_run`` only count, every unused root File family.

    Each page runs in its own transaction, so locks are held briefly and
    progress survives an interrupted run. The session must not be in a
    transaction.
    """
    result = UnusedFileSweepResult(dry_run=dry_run)
    tenants: Counter[str] = Counter()
    after: UUID | None = None
    while True:
        async with session.begin():
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
            if dry_run:
                result.files += len(unused_ids)
            else:
                deleted = await session.execute(
                    sa.delete(Files).where(Files.id.in_(unused_ids))
                )
                result.files += affected_row_count(deleted)
    result.files_by_tenant = dict(sorted(tenants.items()))
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


async def _run_from_cli(*, dry_run: bool) -> UnusedFileSweepResult:
    from eneo.database.database import DatabaseSessionManager
    from eneo.main.config import get_settings

    database = DatabaseSessionManager()
    database.init(get_settings().database_url)
    try:
        async with database.session() as session:
            return await sweep_unused_files(session, dry_run=dry_run)
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
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
