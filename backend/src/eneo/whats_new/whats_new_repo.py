from typing import Literal
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
        return await self._advance(user_id, "seen_version", version)

    async def mark_announced(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._advance(user_id, "announced_version", version)

    async def reset(self, user_id: UUID) -> WhatsNewStatePublic:
        await self.session.execute(
            sa.delete(WhatsNewState).where(WhatsNewState.user_id == user_id)
        )
        return WhatsNewStatePublic(seen_version=None, announced_version=None)

    async def _advance(
        self,
        user_id: UUID,
        marker: Literal["seen_version", "announced_version"],
        version: str,
    ) -> WhatsNewStatePublic:
        # The no-op conflict update locks the row until the request transaction
        # ends and returns its current markers. Unlike read-then-upsert, this
        # also serializes concurrent first writes when no row exists yet.
        # Keep the version comparison under this lock: old tabs cannot undo
        # a newer release recorded by another request.
        stmt = (
            pg_insert(WhatsNewState)
            .values(user_id=user_id)
            .on_conflict_do_update(
                index_elements=[WhatsNewState.user_id],
                set_={"user_id": user_id},
            )
            .returning(WhatsNewState)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalar_one()
        stored = row.seen_version if marker == "seen_version" else row.announced_version
        if stored is None or release_order_key(stored) < release_order_key(version):
            if marker == "seen_version":
                row.seen_version = version
            else:
                row.announced_version = version
            await self.session.flush()
        return WhatsNewStatePublic(
            seen_version=row.seen_version, announced_version=row.announced_version
        )
