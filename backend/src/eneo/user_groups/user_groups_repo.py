# MIT License

from typing import List, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import (
    BaseRepositoryDelegate,
    RelationshipOption,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.main.exceptions import UniqueException
from eneo.user_groups.user_group import (
    UserGroupCreate,
    UserGroupInDB,
    UserGroupState,
    UserGroupUpdate,
)

_NOT_DELETED = sa.or_(
    UserGroups.state.is_(None), UserGroups.state != UserGroupState.DELETED
)


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
        return [
            selectinload(UserGroups.users).selectinload(Users.roles),
            selectinload(UserGroups.users)
            .selectinload(Users.tenant)
            .selectinload(Tenants.modules),
            selectinload(UserGroups.users).selectinload(Users.api_key),
        ]

    async def get_user_group(self, id: UUID) -> UserGroupInDB | None:
        query = (
            sa.select(UserGroups)
            .where(UserGroups.id == id, _NOT_DELETED)
            .options(*self._get_options())
        )
        return await self.delegate.get_model_from_query(query)

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
                    selectinload(Users.tenant).selectinload(Tenants.modules),
                    selectinload(Users.api_key),
                ],
            ),
        ]

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
    ) -> List[UserGroupInDB]:
        query = (
            sa.select(UserGroups)
            .where(UserGroups.tenant_id == tenant_id, _NOT_DELETED)
            .options(*self._get_options())
        )
        return await self.delegate.get_models_from_query(query)
