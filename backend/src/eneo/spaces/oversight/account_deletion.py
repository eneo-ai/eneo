# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""What happens to a tenant administrator's oversight joins when their
account is deleted. Only table imports: user repositories call this."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.spaces_table import SpaceOversightVisits, SpacesUsers


async def end_oversight_of_deleted_user(
    session: AsyncSession, user_id: UUID, *, at: datetime
) -> None:
    """End the user's oversight joins at ``at``: their open visits close, so
    members see them as ended and the daily purge deletes them in time, and
    the memberships they took through oversight go, so a restored account
    reaches the content again only through a new join with a reason. Other
    memberships stay as they are."""
    await session.execute(
        sa.update(SpaceOversightVisits)
        .where(
            SpaceOversightVisits.user_id == user_id,
            SpaceOversightVisits.left_at.is_(None),
        )
        .values(left_at=at)
    )
    await session.execute(
        sa.delete(SpacesUsers).where(
            SpacesUsers.user_id == user_id,
            SpacesUsers.oversight_joined_at.is_not(None),
        )
    )
