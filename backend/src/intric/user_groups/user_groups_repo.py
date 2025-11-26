# MIT License

from typing import List
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import (
    BaseRepositoryDelegate,
    RelationshipOption,
)
from intric.database.tables.user_groups_table import UserGroups
from intric.database.tables.users_table import Users
from intric.main.exceptions import UniqueException
from intric.user_groups.user_group import (
    UserGroupCreate,
    UserGroupInDB,
    UserGroupUpdate,
)


class UserGroupsRepository:
    UNIQUE_EXCEPTION_MSG = "User group name already exists."

    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session,
            UserGroups,
            UserGroupInDB,
            with_options=self._get_options(),
        )

    def _get_options(self):
        return [
            selectinload(UserGroups.users).selectinload(Users.roles),
            selectinload(UserGroups.users).selectinload(Users.predefined_roles),
            selectinload(UserGroups.users).selectinload(Users.tenant),
            selectinload(UserGroups.users).selectinload(Users.api_key),
        ]

    async def get_user_group(self, id: UUID) -> UserGroupInDB:
        return await self.delegate.get(id)

    async def create_user_group(self, user_group: UserGroupCreate) -> UserGroupInDB:
        try:
            return await self.delegate.add(user_group)
        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    @staticmethod
    def _get_relationship_options():
        return [
            RelationshipOption(
                name="users",
                table=Users,
                options=[
                    selectinload(Users.roles),
                    selectinload(Users.predefined_roles),
                    selectinload(Users.tenant),
                    selectinload(Users.api_key),
                ],
            ),
        ]

    async def update_user_group(self, user_group: UserGroupUpdate) -> UserGroupInDB:
        try:
            return await self.delegate.update(
                user_group,
                relationships=self._get_relationship_options(),
            )

        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    async def delete_user_group(self, id: UUID) -> UserGroupInDB:
        return await self.delegate.delete(id)

    async def get_all_user_groups(self, tenant_id: UUID = None) -> List[UserGroupInDB]:
        return await self.delegate.filter_by(
            conditions={UserGroups.tenant_id: tenant_id}
        )
