from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.settings_table import Settings
from intric.settings.settings import SettingsInDB, SettingsUpsert


class SettingsRepository(BaseRepositoryDelegate):
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[SettingsInDB] = BaseRepositoryDelegate(
            session, Settings, SettingsInDB
        )
        self.session = session

    async def add(self, settings: SettingsUpsert):
        return await self.delegate.add(settings)

    async def update(self, settings: SettingsUpsert):
        query = (
            sa.update(Settings)
            .values(**settings.model_dump(exclude_unset=True))
            .where(Settings.user_id == settings.user_id)
            .returning(Settings)
        )

        result = await self.session.execute(query)
        settings_in_db = result.scalar_one()

        return SettingsInDB.model_validate(settings_in_db)

    async def get(self, user_id: UUID):
        query = sa.select(Settings).where(Settings.user_id == user_id)
        result = await self.session.execute(query)
        settings_in_db = result.scalar_one_or_none()

        if not settings_in_db:
            return

        return SettingsInDB.model_validate(settings_in_db)
