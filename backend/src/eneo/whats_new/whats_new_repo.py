from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.database import AsyncSession
from eneo.database.tables.whats_new_table import WhatsNewState
from eneo.whats_new.whats_new_models import WhatsNewStatePublic, release_order_key


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

    async def reset(self, user_id: UUID) -> WhatsNewStatePublic:
        await self.session.execute(
            sa.delete(WhatsNewState).where(WhatsNewState.user_id == user_id)
        )
        return WhatsNewStatePublic(seen_version=None, announced_version=None)

    async def _set(self, user_id: UUID, **column: str) -> WhatsNewStatePublic:
        # Markers only move forward: an older frontend build (e.g. a pod that
        # has not been rolled yet) must not undo what a newer one recorded.
        current = await self.get_state(user_id)
        ((name, version),) = column.items()
        stored = getattr(current, name)
        if stored is not None and release_order_key(stored) >= release_order_key(
            version
        ):
            return current
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
