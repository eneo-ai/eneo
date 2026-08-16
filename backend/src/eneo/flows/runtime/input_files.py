from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

if TYPE_CHECKING:
    from eneo.files.file_models import File, FileInfo
    from eneo.files.file_service import FileService

_RuntimeFile = TypeVar("_RuntimeFile", "File", "FileInfo")


async def load_files_by_requested_ids(
    *,
    file_service: FileService,
    requested_ids: list[UUID],
    file_cache: dict[frozenset[UUID], list["File"]] | None = None,
) -> list["File"]:
    cache_key = frozenset(requested_ids)
    if file_cache is not None and cache_key in file_cache:
        return _order_files_by_requested_ids(
            files=file_cache[cache_key],
            requested_ids=requested_ids,
        )
    files = await file_service.get_files_by_ids(
        file_ids=requested_ids,
        include_transcription=True,
    )
    if file_cache is not None:
        file_cache[cache_key] = files
    return _order_files_by_requested_ids(files=files, requested_ids=requested_ids)


async def describe_files_by_requested_ids(
    *,
    file_service: FileService,
    requested_ids: list[UUID],
) -> list["FileInfo"]:
    """Identify run input files without reading their bytes.

    Audio steps use this and read each payload only while that file is being
    transcribed, so a run's memory cost is one audio file rather than every file
    the step requested. Deliberately uncached: identities are cheap, and a cache
    entry here must never be mistaken for one carrying content.
    """
    described = await file_service.get_owned_file_infos(file_ids=requested_ids)
    return _order_files_by_requested_ids(
        files=described,
        requested_ids=requested_ids,
    )


def _order_files_by_requested_ids(
    *, files: list[_RuntimeFile], requested_ids: list[UUID]
) -> list[_RuntimeFile]:
    file_by_id = {file.id: file for file in files}
    return [
        file_by_id[file_id]
        for file_id in dict.fromkeys(requested_ids)
        if file_id in file_by_id
    ]
