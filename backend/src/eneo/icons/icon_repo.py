from uuid import UUID

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.icons_table import Icons
from eneo.icons.icon import Icon, IconCreate


class IconRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._delegate: BaseRepositoryDelegate[Icon] = BaseRepositoryDelegate(
            session=session, table=Icons, in_db_model=Icon
        )
        self.session = session

    async def add(self, icon: IconCreate) -> Icon:
        return await self._delegate.add(icon)

    async def get(self, icon_id: UUID) -> Icon | None:
        return await self._delegate.get(id=icon_id)

    async def delete(self, icon_id: UUID) -> Icon | None:
        return await self._delegate.delete(icon_id)
