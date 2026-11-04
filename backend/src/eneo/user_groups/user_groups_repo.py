import re
from collections import defaultdict
from collections.abc import Iterable
from typing import List, Optional
from uuid import UUID

import sqlalchemy as sa
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import (
    BaseRepositoryDelegate,
    RelationshipOption,
)
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.main.exceptions import UniqueException
from eneo.user_groups.user_group import (
    UserGroupCreate,
    UserGroupInDB,
    UserGroupInDBBase,
    UserGroupPublic,
    UserGroupState,
    UserGroupUpdate,
)
from eneo.users.user import UserSparse

_NOT_DELETED = sa.or_(
    UserGroups.state.is_(None), UserGroups.state != UserGroupState.DELETED
)


# An address the email validator would return unchanged, or reject.
_PLAIN_EMAIL = re.compile(
    r"(?!.*[xX][nN]--)[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+"
)
_EMAIL: TypeAdapter[str] = TypeAdapter(EmailStr)


def _listed_email(stored: str) -> str:
    """The address as ``UserSparse`` validation gives it, or as stored if rejected.

    Running the validator on every member took most of a 15k-member list's
    second of blocked event loop, and nearly every address is already plain.
    """
    if _PLAIN_EMAIL.fullmatch(stored):
        return stored
    try:
        return _EMAIL.validate_python(stored)
    except ValidationError:
        return stored


async def count_group_users(
    session: AsyncSession, group_ids: Iterable[UUID]
) -> dict[UUID, int]:
    """Users per group, in one grouped query; a group without users is absent.

    Counts the same rows as ``UserGroups.users``: the link's foreign key
    cascades from users, and soft-deleted users stay linked and counted.
    """
    ids = list(group_ids)
    if not ids:
        return {}
    link = usergroups_users_table.c
    rows = await session.execute(
        sa.select(link.user_group_id, sa.func.count())
        .where(link.user_group_id.in_(ids))
        .group_by(link.user_group_id)
    )
    return {group_id: int(count) for group_id, count in rows.tuples()}


class UserGroupsRepository:
    UNIQUE_EXCEPTION_MSG = "User group name already exists."

    def __init__(self, session: AsyncSession):
        super().__init__()
        self.delegate: BaseRepositoryDelegate[UserGroupInDB] = BaseRepositoryDelegate(
            session,
            UserGroups,
            UserGroupInDB,
            with_options=self._get_options(),
        )

    def _get_options(self):
        # The members' roles, tenant and modules are never read; loading them
        # cost a batch of statements per 500 members.
        return [selectinload(UserGroups.users)]

    async def get_user_group(self, id: UUID) -> UserGroupInDB | None:
        query = (
            sa.select(UserGroups)
            .where(UserGroups.id == id, _NOT_DELETED)
            .options(*self._get_options())
        )
        return await self.delegate.get_model_from_query(query)

    async def get_user_group_with_user_count(
        self, id: UUID
    ) -> tuple[UserGroupInDBBase, int] | None:
        """A group and how many users it has, without loading the users."""
        session = self.delegate.session
        record = await session.scalar(
            sa.select(UserGroups).where(UserGroups.id == id, _NOT_DELETED)
        )
        if record is None:
            return None
        counts = await count_group_users(session, [id])
        return UserGroupInDBBase.model_validate(record), counts.get(id, 0)

    async def create_user_group(self, user_group: UserGroupCreate) -> UserGroupInDB:
        try:
            return await self.delegate.add(user_group)
        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    @staticmethod
    def _get_relationship_options():
        return [RelationshipOption(name="users", table=Users)]

    async def update_user_group(
        self, user_group: UserGroupUpdate
    ) -> UserGroupInDB | None:
        try:
            return await self.delegate.update(
                user_group,
                relationships=self._get_relationship_options(),
            )

        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    async def delete_user_group(self, id: UUID) -> UserGroupInDB | None:
        return await self.delegate.delete(id)

    async def get_all_user_groups(
        self, tenant_id: Optional[UUID] = None
    ) -> List[UserGroupPublic]:
        """Built from columns, without validating each member as a model."""
        session = self.delegate.session
        listed = (UserGroups.tenant_id == tenant_id, _NOT_DELETED)
        groups = list(await session.scalars(sa.select(UserGroups).where(*listed)))
        link = usergroups_users_table.c
        rows = await session.execute(
            sa.select(
                link.user_group_id,
                Users.id,
                Users.created_at,
                Users.updated_at,
                Users.email,
                Users.username,
            )
            .join_from(usergroups_users_table, Users)
            .join(UserGroups, UserGroups.id == link.user_group_id)
            .where(*listed)
        )
        members: defaultdict[UUID, list[UserSparse]] = defaultdict(list)
        for group_id, id, created_at, updated_at, email, username in rows.tuples():
            members[group_id].append(
                UserSparse.model_construct(
                    id=id,
                    created_at=created_at,
                    updated_at=updated_at,
                    email=_listed_email(email),
                    username=username,
                )
            )
        return [
            UserGroupPublic.model_construct(
                id=group.id,
                created_at=group.created_at,
                updated_at=group.updated_at,
                name=group.name,
                users=members[group.id],
            )
            for group in groups
        ]
