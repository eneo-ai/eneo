from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.database import AsyncSession
from eneo.database.tables.whats_new_table import WhatsNewSeen
from eneo.whats_new.whats_new_models import WhatsNewSeenPublic


class WhatsNewRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session

    async def get_seen(self, user_id: UUID) -> WhatsNewSeenPublic:
        stmt = sa.select(WhatsNewSeen).where(WhatsNewSeen.user_id == user_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return WhatsNewSeenPublic(version=None, seen_at=None)
        return WhatsNewSeenPublic(version=row.version, seen_at=row.updated_at)

    async def mark_seen(self, user_id: UUID, version: str) -> WhatsNewSeenPublic:
        stmt = (
            pg_insert(WhatsNewSeen)
            .values(user_id=user_id, version=version)
            .on_conflict_do_update(
                index_elements=[WhatsNewSeen.user_id],
                set_={"version": version, "updated_at": sa.func.now()},
            )
            .returning(WhatsNewSeen)
        )
        row = (await self.session.execute(stmt)).scalar_one()
        return WhatsNewSeenPublic(version=row.version, seen_at=row.updated_at)
