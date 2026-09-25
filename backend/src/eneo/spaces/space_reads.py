# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Slim reads about any space of a tenant: its kind and a user's role in it.

Shared by tenant-admin oversight and widgets. Neither loads the space
aggregate, so both are safe for a caller who may see no content.
"""

from collections.abc import Collection
from typing import Literal, Optional, cast
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import higher_role

SpaceKind = Literal["shared", "organization", "personal"]


def space_kind(owner_id: Optional[UUID], tenant_space_id: Optional[UUID]) -> SpaceKind:
    """A personal space has an owner; the organisation space has no parent."""
    if owner_id is not None:
        return "personal"
    if tenant_space_id is None:
        return "organization"
    return "shared"


class SpaceRoleReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def role_in_space(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        user_id: UUID,
        group_ids: Collection[UUID],
    ) -> Optional[SpaceRoleValue]:
        """The user's role in any space of the tenant, as SpaceActor resolves
        it for a signed-in user: the owner of a personal space counts as
        admin, otherwise the higher of the direct role and the roles of
        live groups. None outside the tenant or without a role."""
        direct = (
            sa.select(SpacesUsers.role)
            .where(SpacesUsers.space_id == Spaces.id, SpacesUsers.user_id == user_id)
            .scalar_subquery()
        )
        via_groups = (
            sa.select(sa.func.array_agg(SpacesUserGroups.role))
            .join(
                UserGroups,
                sa.and_(
                    UserGroups.id == SpacesUserGroups.user_group_id,
                    sa.or_(UserGroups.state.is_(None), UserGroups.state != "deleted"),
                ),
            )
            .where(
                SpacesUserGroups.space_id == Spaces.id,
                SpacesUserGroups.user_group_id.in_(list(group_ids)),
            )
            .scalar_subquery()
        )
        stmt = sa.select(Spaces.user_id, direct, via_groups).where(
            Spaces.id == space_id, Spaces.tenant_id == tenant_id
        )
        row = (await self.session.execute(stmt)).tuples().one_or_none()
        if row is None:
            return None
        owner_id, direct_role, group_roles = row
        if owner_id is not None:
            return SpaceRoleValue.ADMIN if owner_id == user_id else None
        # Scalar subquery: None without a direct row.
        role = (
            SpaceRoleValue(direct_role)
            if cast(Optional[str], direct_role) is not None
            else None
        )
        for group_role in cast(Optional[list[str]], group_roles) or []:
            role = higher_role(role, SpaceRoleValue(group_role))
        return role
