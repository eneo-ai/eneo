from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.settings_table import Settings
from eneo.settings.settings import SettingsInDB, SettingsUpsert


class SettingsRepository:
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.delegate: BaseRepositoryDelegate[SettingsInDB] = BaseRepositoryDelegate(
            session, Settings, SettingsInDB
        )
        self.session = session

    async def add(self, settings: SettingsUpsert) -> SettingsInDB:
        return await self.delegate.add(settings)

    async def update(self, settings: SettingsUpsert) -> SettingsInDB:
        query = (
            sa.update(Settings)
            .values(**settings.model_dump(exclude_unset=True))
            .where(Settings.user_id == settings.user_id)  # type: ignore[reportUnknownMemberType]
            .returning(Settings)
        )

        result = await self.session.execute(query)
        settings_in_db = result.scalar_one()

        return SettingsInDB.model_validate(settings_in_db)

    async def get(self, user_id: UUID) -> SettingsInDB | None:
        query = sa.select(Settings).where(Settings.user_id == user_id)  # type: ignore[reportUnknownMemberType]
        result = await self.session.execute(query)
        settings_in_db = result.scalar_one_or_none()

        if not settings_in_db:
            return

        return SettingsInDB.model_validate(settings_in_db)
