from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from intric.files.file_models import File


def parse_requested_file_ids(*, raw_file_ids: Any) -> list[UUID]:
    if raw_file_ids is None:
        return []
    if not isinstance(raw_file_ids, list):
        raise TypedIOValidationException(
            "file_ids must be a list.",
            code="typed_io_invalid_file_ids",
        )
    try:
        return [UUID(str(file_id)) for file_id in raw_file_ids]
    except (TypeError, ValueError, AttributeError) as exc:
        raise TypedIOValidationException(
            f"Invalid file_ids payload: {raw_file_ids}",
            code="typed_io_invalid_file_ids",
        ) from exc


async def load_files_by_requested_ids(
    *,
    file_repo: Any,
    requested_ids: list[UUID],
    user_id: UUID,
    file_cache: dict[frozenset[UUID], list["File"]] | None = None,
) -> list["File"]:
    cache_key = frozenset(requested_ids)
    if file_cache is not None and cache_key in file_cache:
        return file_cache[cache_key]
    files = await file_repo.get_list_by_id_and_user(requested_ids, user_id=user_id)
    if file_cache is not None:
        file_cache[cache_key] = files
    return files
