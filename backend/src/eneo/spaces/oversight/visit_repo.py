# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Oversight visits: when a tenant administrator joined a space through
oversight, with which role and reason, and when that membership ended."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.spaces_table import SpaceOversightVisits
from eneo.database.tables.users_table import Users
from eneo.spaces.api.space_models import SpaceRoleValue


@dataclass(frozen=True)
class OversightVisitRow:
    # None once the user is deleted.
    user_id: Optional[UUID]
    name: Optional[str]
    role: SpaceRoleValue
    reason: str
    joined_at: datetime
    left_at: Optional[datetime]


class OversightVisitRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
        role: SpaceRoleValue,
        reason: str,
        joined_at: datetime,
    ) -> None:
        await self.session.execute(
            sa.insert(SpaceOversightVisits).values(
                tenant_id=tenant_id,
                space_id=space_id,
                user_id=user_id,
                role=role.value,
                reason=reason,
                joined_at=joined_at,
            )
        )

    async def close(self, space_id: UUID, user_id: UUID, *, left_at: datetime) -> None:
        """End the user's open visit to the space, if they have one: the
        membership it recorded is gone, however it was removed."""
        await self.session.execute(
            sa.update(SpaceOversightVisits)
            .where(
                SpaceOversightVisits.space_id == space_id,
                SpaceOversightVisits.user_id == user_id,
                SpaceOversightVisits.left_at.is_(None),
            )
            .values(left_at=left_at)
        )

    async def recent(
        self, space_id: UUID, *, since: datetime
    ) -> list[OversightVisitRow]:
        """Open visits and those that ended after ``since``, newest first."""
        stmt = (
            sa.select(
                SpaceOversightVisits.user_id,
                sa.case(
                    (
                        Users.deleted_at.is_(None),
                        sa.func.coalesce(Users.username, Users.email),
                    ),
                    else_=sa.null(),
                ),
                SpaceOversightVisits.role,
                SpaceOversightVisits.reason,
                SpaceOversightVisits.joined_at,
                SpaceOversightVisits.left_at,
            )
            .outerjoin(Users, Users.id == SpaceOversightVisits.user_id)
            .where(
                SpaceOversightVisits.space_id == space_id,
                sa.or_(
                    SpaceOversightVisits.left_at.is_(None),
                    SpaceOversightVisits.left_at >= since,
                ),
            )
            .order_by(SpaceOversightVisits.joined_at.desc(), SpaceOversightVisits.id)
        )
        return [
            OversightVisitRow(
                user_id=user_id if name is not None else None,
                name=name,
                role=SpaceRoleValue(role),
                reason=reason,
                joined_at=joined_at,
                left_at=left_at,
            )
            for user_id, name, role, reason, joined_at, left_at in (
                await self.session.execute(stmt)
            ).tuples()
        ]
