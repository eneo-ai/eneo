from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from eneo.flows.principal import FlowPrincipal

if TYPE_CHECKING:
    from eneo.files.file_models import File


class RuntimeInputFileRepository(Protocol):
    async def get_list_by_id_for_owner(
        self,
        *,
        ids: list[UUID],
        owner_type: str,
        owner_user_id: UUID | None = None,
        owner_service_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> list["File"]: ...


async def load_files_by_requested_ids(
    *,
    file_repo: RuntimeInputFileRepository,
    requested_ids: list[UUID],
    principal: FlowPrincipal,
    tenant_id: UUID,
    file_cache: dict[frozenset[UUID], list["File"]] | None = None,
) -> list["File"]:
    cache_key = frozenset(requested_ids)
    if file_cache is not None and cache_key in file_cache:
        return _order_files_by_requested_ids(
            files=file_cache[cache_key],
            requested_ids=requested_ids,
        )
    files = await file_repo.get_list_by_id_for_owner(
        ids=requested_ids,
        owner_type=principal.principal_type.value,
        owner_user_id=principal.principal_user_id,
        owner_service_id=principal.principal_service_id,
        tenant_id=tenant_id,
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
