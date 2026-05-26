from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from intric.files.file_models import File


class RuntimeInputFileRepository(Protocol):
    async def get_list_by_id_for_owner(
        self,
        *,
        ids: list[UUID],
        owner_type: str,
        owner_user_id: UUID | None = None,
        owner_api_key_id: UUID | None = None,
        include_transcription: bool = True,
    ) -> list["File"]: ...


def parse_requested_file_ids(*, raw_file_ids: object) -> list[UUID]:
    if raw_file_ids is None:
        return []
    if not isinstance(raw_file_ids, list):
        raise TypedIOValidationException(
            "file_ids must be a list.",
            code="typed_io_invalid_file_ids",
        )
    file_ids = cast(list[object], raw_file_ids)
    try:
        return [UUID(str(file_id)) for file_id in file_ids]
    except (TypeError, ValueError, AttributeError) as exc:
        raise TypedIOValidationException(
            f"Invalid file_ids payload: {raw_file_ids}",
            code="typed_io_invalid_file_ids",
        ) from exc


async def load_files_by_requested_ids(
    *,
    file_repo: RuntimeInputFileRepository,
    requested_ids: list[UUID],
    principal: FlowPrincipal,
    file_cache: dict[frozenset[UUID], list["File"]] | None = None,
) -> list["File"]:
    cache_key = frozenset(requested_ids)
    if file_cache is not None and cache_key in file_cache:
        return file_cache[cache_key]
    files = await file_repo.get_list_by_id_for_owner(
        ids=requested_ids,
        owner_type=principal.principal_type.value,
        owner_user_id=principal.principal_user_id,
        owner_api_key_id=principal.principal_api_key_id,
    )
    if file_cache is not None:
        file_cache[cache_key] = files
    return files
