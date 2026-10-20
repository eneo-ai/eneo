from datetime import datetime, timedelta, timezone
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
            seen_version=row.seen_version,
            announced_version=row.announced_version,
            remind_after=row.remind_after,
        )

    async def mark_seen(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._record(user_id, "seen", version)

    async def mark_announced(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._record(user_id, "announced", version)

    async def snooze(self, user_id: UUID, version: str) -> WhatsNewStatePublic:
        return await self._record(user_id, "snooze", version)

    async def reset(self, user_id: UUID) -> WhatsNewStatePublic:
        await self.session.execute(
            sa.delete(WhatsNewState).where(WhatsNewState.user_id == user_id)
        )
        return WhatsNewStatePublic(seen_version=None, announced_version=None)

    async def _record(
        self,
        user_id: UUID,
        action: Literal["seen", "announced", "snooze"],
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
        version_key = release_order_key(version)
        if action == "seen":
            if (
                row.seen_version is None
                or release_order_key(row.seen_version) < version_key
            ):
                row.seen_version = version
            if row.announced_version is not None and version_key >= release_order_key(
                row.announced_version
            ):
                row.remind_after = None
        elif row.announced_version is None or version_key >= release_order_key(
            row.announced_version
        ):
            # A stale tab cannot defer an older release or revive already read news.
            row.announced_version = version
            unread = row.seen_version is None or version_key > release_order_key(
                row.seen_version
            )
            row.remind_after = (
                datetime.now(timezone.utc) + timedelta(hours=24)
                if action == "snooze" and unread
                else None
            )
        await self.session.flush()
        return WhatsNewStatePublic(
            seen_version=row.seen_version,
            announced_version=row.announced_version,
            remind_after=row.remind_after,
        )
