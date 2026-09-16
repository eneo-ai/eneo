from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.database import AsyncSession
from eneo.database.tables.whats_new_table import WhatsNewState
from eneo.whats_new.whats_new_models import WhatsNewStatePublic


class WhatsNewRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session

    async def get_state(self, user_id: UUID) -> WhatsNewStatePublic:
        stmt = sa.select(WhatsNewState).where(WhatsNewState.user_id == user_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return WhatsNewStatePublic(seen_version=None, announced_version=None)
        return WhatsNewStatePublic(
            seen_version=row.seen_version, announced_version=row.announced_version
        )

    async def mark_seen(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._set(user_id, seen_version=version)

    async def mark_announced(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._set(user_id, announced_version=version)

    async def _set(self, user_id: UUID, **column: str) -> WhatsNewStatePublic:
        stmt = (
            pg_insert(WhatsNewState)
            .values(user_id=user_id, **column)
            .on_conflict_do_update(
                index_elements=[WhatsNewState.user_id],
                set_={**column, "updated_at": sa.func.now()},
            )
            .returning(WhatsNewState)
        )
        row = (await self.session.execute(stmt)).scalar_one()
        return WhatsNewStatePublic(
            seen_version=row.seen_version, announced_version=row.announced_version
        )
