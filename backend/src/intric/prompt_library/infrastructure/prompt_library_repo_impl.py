# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.tables.prompt_library_table import PromptLibrary
from intric.prompt_library.domain.prompt_library import PromptLibraryEntry


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
                created_by_user_id=entry.created_by_user_id,
            )
            .returning(PromptLibrary)
            .options(selectinload(PromptLibrary.created_by))
        )
        row = await self.session.scalar(stmt)
        assert row is not None
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

    async def list_by_tenant(self, tenant_id: UUID) -> list[PromptLibraryEntry]:
        stmt = (
            sa.select(PromptLibrary)
            .where(PromptLibrary.tenant_id == tenant_id)
            .order_by(PromptLibrary.name)
        )
        result = await self.session.scalars(stmt)
        return [self._to_domain(row) for row in result.all()]

    async def update(self, entry: PromptLibraryEntry) -> PromptLibraryEntry:
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
            )
            .returning(PromptLibrary)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        return self._to_domain(row)

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
