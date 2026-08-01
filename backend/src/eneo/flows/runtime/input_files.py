from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService


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


def _order_files_by_requested_ids(
    *, files: list["File"], requested_ids: list[UUID]
) -> list["File"]:
    file_by_id = {file.id: file for file in files}
    return [
        file_by_id[file_id]
        for file_id in dict.fromkeys(requested_ids)
        if file_id in file_by_id
    ]
