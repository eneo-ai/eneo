from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import defer

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.files_table import Files
from intric.files.file_models import File, FileCreate, FileInfo


class FileRepository:
    def __init__(self, session: AsyncSession):
        self._delegate = BaseRepositoryDelegate(
            session=session, table=Files, in_db_model=File
        )
        self.session = session

    async def add(self, file: FileCreate) -> File:
        return await self._delegate.add(file)

    async def get_list_by_id_and_user(
        self, ids: list[UUID], user_id: UUID, include_transcription: bool = True
    ) -> list[File]:
        stmt = (
            sa.select(Files)
            .where(Files.id.in_(ids))
            .where(Files.user_id == user_id)
            .order_by(Files.created_at)
        )

        if not include_transcription:
            stmt = stmt.options(defer(Files.transcription, raiseload=True))

        files_in_db = await self.session.scalars(stmt)

        files = [File.model_validate(file) for file in files_in_db]

        return files

    async def get_list_by_id_and_tenant(
        self, ids: list[UUID], tenant_id: UUID, include_transcription: bool = True
    ) -> list[File]:
        stmt = (
            sa.select(Files)
            .where(Files.id.in_(ids))
            .where(Files.tenant_id == tenant_id)
            .order_by(Files.created_at)
        )

        if not include_transcription:
            stmt = stmt.options(defer(Files.transcription, raiseload=True))

        files_in_db = await self.session.scalars(stmt)

        return [File.model_validate(file) for file in files_in_db]

    async def get_by_id(self, file_id: UUID) -> File:
        file = await self._delegate.get(id=file_id)
        return File.model_validate(file)

    async def get_list_by_user(self, user_id: UUID) -> list[File]:
        return await self._delegate.filter_by(conditions={Files.user_id: user_id})

    async def get_by_checksum(self, checksum: str) -> File:
        return await self._delegate.get_by(conditions={Files.checksum: checksum})

    async def delete(self, id: UUID) -> File:
        return await self._delegate.delete(id)

    async def update(self, file: File) -> File:
        return await self._delegate.update(file)

    async def get_file_infos(self, ids: list[UUID]) -> list[FileInfo]:
        stmt = (
            sa.select(Files)
            .where(Files.id.in_(ids))
            .options(
                defer(Files.text, raiseload=True),
                defer(Files.blob, raiseload=True),
                defer(Files.transcription, raiseload=True),
            )
        )

        files_in_db = await self.session.scalars(stmt)

        return [FileInfo.model_validate(file) for file in files_in_db]
