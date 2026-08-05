import asyncio
import contextlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.job_table import Jobs
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

STAGING_RECONCILE_PAGE_SIZE = 50
ORPHAN_STAGING_DELETE_LIMIT = 50
ORPHAN_STAGING_QUERY_BATCH_SIZE = 50
ORPHAN_STAGING_GRACE_PERIOD = timedelta(hours=1)
_TERMINAL_STATUS_SQL = (
    sa.literal_column("'complete'", type_=sa.String()),
    sa.literal_column("'failed'", type_=sa.String()),
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class StagingReconciliationResult:
    terminal_cleaned: int
    orphans_deleted: int


def _job_staging_directory(*, upload_tmp_dir: Path | None = None) -> Path:
    root = upload_tmp_dir or get_settings().upload_tmp_dir
    return root / "job-staging"


def job_staging_path(job_id: UUID, *, upload_tmp_dir: Path | None = None) -> Path:
    return _job_staging_directory(upload_tmp_dir=upload_tmp_dir) / str(job_id)


def terminal_staging_jobs_statement():
    return (
        sa.select(Jobs)
        .where(Jobs.dispatch_envelope.is_not(None))
        .where(Jobs.status.in_(_TERMINAL_STATUS_SQL))
        .where(Jobs.staging_cleaned_at.is_(None))
        .order_by(Jobs.finished_at.asc().nullsfirst(), Jobs.id.asc())
        .limit(STAGING_RECONCILE_PAGE_SIZE)
        .with_for_update(skip_locked=True)
    )


async def _delete_orphan_staged_files(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    staging_directory = _job_staging_directory()
    cutoff = now - ORPHAN_STAGING_GRACE_PERIOD
    # The DB-driven pass keeps this directory small. A full scan ensures rare
    # pre-commit orphans are reached even when active files sort first, so a
    # persisted filesystem cursor is not warranted. Discovery runs off the event
    # loop and candidates reach PostgreSQL in fixed batches to bound each query.
    candidates = await asyncio.to_thread(
        _discover_old_staged_files,
        staging_directory,
        cutoff,
    )
    deleted = 0
    for offset in range(0, len(candidates), ORPHAN_STAGING_QUERY_BATCH_SIZE):
        batch = candidates[offset : offset + ORPHAN_STAGING_QUERY_BATCH_SIZE]
        existing_ids = set(
            (
                await session.scalars(
                    sa.select(Jobs.id).where(
                        Jobs.id.in_([job_id for job_id, _ in batch])
                    )
                )
            ).all()
        )
        for job_id, path in batch:
            if job_id in existing_ids:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Orphaned job staging cleanup failed",
                    extra={"job_id": str(job_id), "error": str(exc)},
                )
                continue
            deleted += 1
            if deleted >= ORPHAN_STAGING_DELETE_LIMIT:
                return deleted
    return deleted


def _discover_old_staged_files(
    staging_directory: Path,
    cutoff: datetime,
) -> list[tuple[UUID, Path]]:
    if not staging_directory.exists():
        return []

    candidates: list[tuple[UUID, Path]] = []
    for path in staging_directory.iterdir():
        try:
            job_id = UUID(path.name)
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if path.is_file() and modified_at <= cutoff:
            candidates.append((job_id, path))
    return candidates


async def reconcile_job_staging(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> StagingReconciliationResult:
    cleaned_at = now or datetime.now(timezone.utc)
    jobs = list((await session.scalars(terminal_staging_jobs_statement())).all())
    terminal_cleaned = 0
    for job in jobs:
        try:
            job_staging_path(job.id).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "Terminal job staging cleanup failed",
                extra={"job_id": str(job.id), "error": str(exc)},
            )
            continue
        job.staging_cleaned_at = cleaned_at
        terminal_cleaned += 1
    await session.flush()

    orphans_deleted = await _delete_orphan_staged_files(session, now=cleaned_at)
    return StagingReconciliationResult(
        terminal_cleaned=terminal_cleaned,
        orphans_deleted=orphans_deleted,
    )


async def stage_job_file(file: IO[bytes], job_id: UUID) -> Path:
    destination = job_staging_path(job_id)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with destination.open("wb") as buffer:
            await asyncio.to_thread(shutil.copyfileobj, file, buffer)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            destination.unlink()
        raise
    finally:
        file.close()

    return destination
