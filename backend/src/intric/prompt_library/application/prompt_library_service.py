# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from intric.main.exceptions import BadRequestException, NotFoundException
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.prompt_library.domain.prompt_library import PromptLibraryEntry
from intric.prompt_library.domain.prompt_library_repo import PromptLibraryRepo
from intric.roles.permissions import Permission, validate_permission
from intric.users.user import UserInDB


class PromptLibraryService:
    def __init__(
        self,
        user: UserInDB,
        repo: PromptLibraryRepo,
    ) -> None:
        self.user = user
        self.repo = repo

    async def list_entries(self) -> list[PromptLibraryEntry]:
        validate_permission(self.user, Permission.ADMIN)
        return await self.repo.list_by_tenant(self.user.tenant_id)

    async def get_entry(self, id: UUID) -> PromptLibraryEntry:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.repo.get(id=id, tenant_id=self.user.tenant_id)
        if entry is None:
            raise NotFoundException()
        return entry

    async def create_entry(
        self,
        *,
        name: str,
        description: str | None,
        text: str,
    ) -> PromptLibraryEntry:
        validate_permission(self.user, Permission.ADMIN)
        if not name.strip():
            raise BadRequestException("name cannot be empty")
        if not text.strip():
            raise BadRequestException("text cannot be empty")
        if await self.repo.exists_by_name(self.user.tenant_id, name):
            raise BadRequestException(f"A prompt named '{name}' already exists")

        entry = PromptLibraryEntry(
            id=None,
            tenant_id=self.user.tenant_id,
            name=name,
            description=description,
            text=text,
            created_by_user_id=self.user.id,
            created_at=None,
            updated_at=None,
        )
        return await self.repo.add(entry)

    async def update_entry(
        self,
        id: UUID,
        *,
        name: str | None = None,
        description: str | None | NotProvided = NOT_PROVIDED,
        text: str | None = None,
    ) -> PromptLibraryEntry:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.get_entry(id)

        if name is not None and name != entry.name:
            if await self.repo.exists_by_name(
                self.user.tenant_id, name, exclude_id=entry.id
            ):
                raise BadRequestException(f"A prompt named '{name}' already exists")

        entry.update(name=name, description=description, text=text)
        return await self.repo.update(entry)

    async def delete_entry(self, id: UUID) -> None:
        validate_permission(self.user, Permission.ADMIN)
        await self.get_entry(id)
        await self.repo.delete(id=id, tenant_id=self.user.tenant_id)
