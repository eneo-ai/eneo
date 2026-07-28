import asyncio
import contextlib
import shutil
from pathlib import Path
from typing import IO
from uuid import UUID

from eneo.main.config import get_settings


def job_staging_path(job_id: UUID, *, upload_tmp_dir: Path | None = None) -> Path:
    root = upload_tmp_dir or get_settings().upload_tmp_dir
    return root / "job-staging" / str(job_id)


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
