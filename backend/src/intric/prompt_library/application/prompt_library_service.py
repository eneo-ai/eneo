# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from intric.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
)
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.prompt_library.domain.prompt_library import (
    PromptLibraryEntry,
    PromptLibraryVersion,
)
from intric.prompt_library.domain.prompt_library_repo import PromptLibraryRepo
from intric.roles.permissions import Permission, validate_permission
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.governance_policy.domain.governance_policy_repo import (
        GovernancePolicyRepo,
    )


_NAME_UNIQUE_CONSTRAINT = "uq_prompt_library_tenant_name"


class PromptLibraryService:
    def __init__(
        self,
        user: UserInDB,
        repo: PromptLibraryRepo,
        governance_policy_repo: Optional["GovernancePolicyRepo"] = None,
    ) -> None:
        self.user = user
        self.repo = repo
        # Optional dependency: when Phase 2 is in place, deletes consult the
        # policy repo so we can give a friendly 409 instead of a raw FK violation.
        self.governance_policy_repo = governance_policy_repo

    async def list_entries(self) -> list[PromptLibraryEntry]:
        validate_permission(self.user, Permission.ADMIN)
        return await self.repo.list_by_tenant(self.user.tenant_id)

    async def get_entry(self, id: UUID) -> PromptLibraryEntry:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.repo.get(id=id, tenant_id=self.user.tenant_id)
        if entry is None:
            raise NotFoundException()
        return entry

    async def get_entry_for_update(self, id: UUID) -> PromptLibraryEntry:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.repo.get_for_update(id=id, tenant_id=self.user.tenant_id)
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
        # Pre-check for the friendly message in the common case; the IntegrityError
        # below closes the TOCTOU race between this check and the insert.
        if await self.repo.exists_by_name(self.user.tenant_id, name):
            raise BadRequestException(f"A prompt named '{name}' already exists")

        entry = PromptLibraryEntry(
            id=None,
            tenant_id=self.user.tenant_id,
            name=name,
            description=description,
            text=text,
            current_version=1,
            created_by_user_id=self.user.id,
            created_at=None,
            updated_at=None,
        )
        try:
            return await self.repo.add(entry)
        except IntegrityError as e:
            raise self._name_collision_or_reraise(name, e)

    async def update_entry(
        self,
        id: UUID,
        *,
        name: str | None = None,
        description: str | None | NotProvided = NOT_PROVIDED,
        text: str | None = None,
    ) -> PromptLibraryEntry:
        entry = await self.get_entry_for_update(id)

        if name is not None and name != entry.name:
            if await self.repo.exists_by_name(
                self.user.tenant_id, name, exclude_id=entry.id
            ):
                raise BadRequestException(f"A prompt named '{name}' already exists")

        old_name = entry.name
        old_description = entry.description
        old_text = entry.text
        old_version = entry.current_version
        entry.update(name=name, description=description, text=text)

        create_version = (
            entry.name != old_name
            or entry.description != old_description
            or entry.text != old_text
        )
        if create_version:
            entry.current_version = old_version + 1

        try:
            return await self.repo.update(
                entry,
                create_version=create_version,
                version_created_by_user_id=self.user.id,
            )
        except IntegrityError as e:
            raise self._name_collision_or_reraise(entry.name, e)

    @staticmethod
    def _name_collision_or_reraise(name: str, error: IntegrityError) -> Exception:
        """Translate the tenant+name unique violation into the same 400 the
        pre-check raises; re-raise anything else (e.g. an FK violation is a real
        500, not a name collision)."""
        if _NAME_UNIQUE_CONSTRAINT in str(error.orig):
            return BadRequestException(f"A prompt named '{name}' already exists")
        return error

    async def list_versions(self, id: UUID) -> list[PromptLibraryVersion]:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.get_entry(id)
        assert entry.id is not None
        return await self.repo.list_versions(
            prompt_library_id=entry.id,
            tenant_id=self.user.tenant_id,
        )

    async def delete_entry(self, id: UUID) -> None:
        validate_permission(self.user, Permission.ADMIN)
        entry = await self.get_entry(id)

        # Belt-and-suspenders: the FK has ON DELETE RESTRICT so the DB will
        # refuse the delete anyway, but consulting the policy repo first lets
        # us give a friendly error with context instead of a 500.
        if self.governance_policy_repo is not None:
            policy = await self.governance_policy_repo.get_by_prompt_library_id(
                tenant_id=self.user.tenant_id, prompt_library_id=id
            )
            if policy is not None:
                raise NameCollisionException(
                    f"Prompt '{entry.name}' is referenced by the personal "
                    f"assistant governance policy. Unset it on the policy before deleting."
                )

        await self.repo.delete(id=id, tenant_id=self.user.tenant_id)
