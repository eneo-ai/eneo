# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from intric.prompt_library.domain.prompt_library import (
    PromptLibraryEntry,
    PromptLibraryVersion,
)


class PromptLibraryRepo(Protocol):
    async def add(self, entry: PromptLibraryEntry) -> PromptLibraryEntry: ...

    async def get(self, id: UUID, tenant_id: UUID) -> PromptLibraryEntry | None: ...

    async def get_for_update(
        self, id: UUID, tenant_id: UUID
    ) -> PromptLibraryEntry | None: ...

    async def list_by_tenant(self, tenant_id: UUID) -> list[PromptLibraryEntry]: ...

    async def update(
        self,
        entry: PromptLibraryEntry,
        *,
        create_version: bool,
        version_created_by_user_id: UUID,
    ) -> PromptLibraryEntry: ...

    async def list_versions(
        self, prompt_library_id: UUID, tenant_id: UUID
    ) -> list[PromptLibraryVersion]: ...

    async def delete(self, id: UUID, tenant_id: UUID) -> None: ...

    async def exists_by_name(
        self,
        tenant_id: UUID,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool: ...
