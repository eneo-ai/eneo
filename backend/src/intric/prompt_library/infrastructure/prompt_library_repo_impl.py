# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.tables.prompt_library_table import (
    PromptLibrary,
    PromptLibraryVersions,
)
from intric.prompt_library.domain.prompt_library import (
    PromptLibraryEntry,
    PromptLibraryVersion,
)


class PromptLibraryRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_domain(row: PromptLibrary) -> PromptLibraryEntry:
        return PromptLibraryEntry(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            text=row.text,
            current_version=row.current_version,
            created_by_user_id=row.created_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_version_domain(row: PromptLibraryVersions) -> PromptLibraryVersion:
        return PromptLibraryVersion(
            id=row.id,
            prompt_library_id=row.prompt_library_id,
            tenant_id=row.tenant_id,
            version=row.version,
            name=row.name,
            description=row.description,
            text=row.text,
            created_by_user_id=row.created_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, entry: PromptLibraryEntry) -> PromptLibraryEntry:
        stmt = (
            sa.insert(PromptLibrary)
            .values(
                tenant_id=entry.tenant_id,
                name=entry.name,
                description=entry.description,
                text=entry.text,
                current_version=1,
                created_by_user_id=entry.created_by_user_id,
            )
            .returning(PromptLibrary)
            .options(selectinload(PromptLibrary.created_by))
        )
        row = await self.session.scalar(stmt)
        assert row is not None

        await self.session.execute(
            sa.insert(PromptLibraryVersions).values(
                prompt_library_id=row.id,
                tenant_id=row.tenant_id,
                version=row.current_version,
                name=row.name,
                description=row.description,
                text=row.text,
                created_by_user_id=row.created_by_user_id,
            )
        )
        return self._to_domain(row)

    async def get(self, id: UUID, tenant_id: UUID) -> PromptLibraryEntry | None:
        stmt = sa.select(PromptLibrary).where(
            PromptLibrary.id == id,
            PromptLibrary.tenant_id == tenant_id,
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return self._to_domain(row)

    async def get_for_update(
        self, id: UUID, tenant_id: UUID
    ) -> PromptLibraryEntry | None:
        stmt = (
            sa.select(PromptLibrary)
            .where(
                PromptLibrary.id == id,
                PromptLibrary.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return self._to_domain(row)

    async def list_by_tenant(self, tenant_id: UUID) -> list[PromptLibraryEntry]:
        stmt = (
            sa.select(PromptLibrary)
            .where(PromptLibrary.tenant_id == tenant_id)
            .order_by(PromptLibrary.name)
        )
        result = await self.session.scalars(stmt)
        return [self._to_domain(row) for row in result.all()]

    async def update(
        self,
        entry: PromptLibraryEntry,
        *,
        create_version: bool,
        version_created_by_user_id: UUID,
    ) -> PromptLibraryEntry:
        assert entry.id is not None
        stmt = (
            sa.update(PromptLibrary)
            .where(
                PromptLibrary.id == entry.id,
                PromptLibrary.tenant_id == entry.tenant_id,
            )
            .values(
                name=entry.name,
                description=entry.description,
                text=entry.text,
                current_version=entry.current_version,
            )
            .returning(PromptLibrary)
        )
        row = await self.session.scalar(stmt)
        assert row is not None

        if create_version:
            await self.session.execute(
                sa.insert(PromptLibraryVersions).values(
                    prompt_library_id=row.id,
                    tenant_id=row.tenant_id,
                    version=row.current_version,
                    name=row.name,
                    description=row.description,
                    text=row.text,
                    created_by_user_id=version_created_by_user_id,
                )
            )

        return self._to_domain(row)

    async def list_versions(
        self, prompt_library_id: UUID, tenant_id: UUID
    ) -> list[PromptLibraryVersion]:
        stmt = (
            sa.select(PromptLibraryVersions)
            .where(
                PromptLibraryVersions.prompt_library_id == prompt_library_id,
                PromptLibraryVersions.tenant_id == tenant_id,
            )
            .order_by(PromptLibraryVersions.version.desc())
        )
        result = await self.session.scalars(stmt)
        return [self._to_version_domain(row) for row in result.all()]

    async def delete(self, id: UUID, tenant_id: UUID) -> None:
        stmt = sa.delete(PromptLibrary).where(
            PromptLibrary.id == id,
            PromptLibrary.tenant_id == tenant_id,
        )
        await self.session.execute(stmt)

    async def exists_by_name(
        self,
        tenant_id: UUID,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        stmt = (
            sa.select(sa.func.count())
            .select_from(PromptLibrary)
            .where(
                PromptLibrary.tenant_id == tenant_id,
                PromptLibrary.name == name,
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(PromptLibrary.id != exclude_id)
        count = await self.session.scalar(stmt)
        return bool(count)
