# MIT License

from uuid import UUID

from eneo.main.exceptions import AuthenticationException, NotFoundException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission, validate_permissions
from eneo.user_groups.user_group import (
    UserGroupCreate,
    UserGroupCreateRequest,
    UserGroupInDB,
    UserGroupUpdate,
    UserGroupUpdateRequest,
)
from eneo.user_groups.user_groups_repo import UserGroupsRepository
from eneo.users.user import UserInDB


class UserGroupsService:
    def __init__(
        self,
        user: UserInDB,
        repo: UserGroupsRepository,
    ):
        self.user = user
        self.repo = repo

    def _validate(self, user_group: UserGroupInDB, user_group_uuid: UUID):
        if user_group is None or self.user.tenant_id != user_group.tenant_id:
            raise NotFoundException(f"User group {user_group_uuid} not found")

    def _check_users_relationships(self, user_group: UserGroupInDB):
        for user in user_group.users:
            if user.tenant_id != user_group.tenant_id:
                raise AuthenticationException(
                    f"User {self.user.id} tried to add user {user.id} "
                    f"to group {user_group.id}"
                )

    def _check_relationships(self, user_group: UserGroupInDB):
        self._check_users_relationships(user_group)

    @validate_permissions(Permission.ADMIN)
    async def create_user_group(
        self, user_group: UserGroupCreateRequest
    ) -> UserGroupInDB:
        user_group = UserGroupCreate(
            name=user_group.name, tenant_id=self.user.tenant_id
        )
        return await self.repo.create_user_group(user_group)

    @validate_permissions(Permission.ADMIN)
    async def get_user_group_by_uuid(self, user_group_uuid: UUID) -> UserGroupInDB:
        user_group = await self.repo.get_user_group(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return user_group

    @validate_permissions(Permission.ADMIN)
    async def update_user_group(
        self, user_group_update: UserGroupUpdateRequest, user_group_uuid: UUID
    ):
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        user_group_update = UserGroupUpdate(
            **user_group_update.model_dump(exclude_unset=True), id=user_group.id
        )
        user_group = await self.repo.update_user_group(user_group_update)

        # check all the relationships and raise exceptions if needed
        self._check_relationships(user_group)

        return user_group

    @validate_permissions(Permission.ADMIN)
    async def delete_user_group(self, user_group_uuid: UUID):
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return await self.repo.delete_user_group(user_group_uuid)

    @validate_permissions(Permission.ADMIN)
    async def get_all_user_groups(self):
        return await self.repo.get_all_user_groups(self.user.tenant_id)

    def _append_items_list(
        self,
        user_group: UserGroupInDB,
        relationship: str,
        item_uuid: UUID,
        attr_name: str,
    ):
        uuid_list = [
            getattr(item, attr_name) for item in getattr(user_group, relationship)
        ]

        if item_uuid not in uuid_list:
            uuid_list.append(item_uuid)

        return [ModelId(id=item) for item in uuid_list]

    async def append_items(
        self,
        user_group: UserGroupInDB,
        relationship: str,
        item_uuid: UUID,
        attr_name: str = "uuid",
    ):
        items = self._append_items_list(
            user_group=user_group,
            relationship=relationship,
            item_uuid=item_uuid,
            attr_name=attr_name,
        )

        user_group_in = UserGroupUpdate(id=user_group.id)
        setattr(user_group_in, relationship, items)

        user_group = await self.repo.update_user_group(user_group_in)

        # check all the relationships and raise exceptions if needed
        self._check_relationships(user_group)

        return user_group

    def _pop_items_list(
        self,
        user_group: UserGroupInDB,
        relationship: str,
        item_uuid: UUID,
        attr_name: str,
    ):
        uuid_list = [
            getattr(item, attr_name) for item in getattr(user_group, relationship)
        ]

        if item_uuid in uuid_list:
            uuid_list.remove(item_uuid)

        return [ModelId(id=item) for item in uuid_list]

    async def pop_items(
        self,
        user_group: UserGroupInDB,
        relationship: str,
        item_uuid: UUID,
        attr_name="uuid",
    ):
        items = self._pop_items_list(
            user_group=user_group,
            relationship=relationship,
            item_uuid=item_uuid,
            attr_name=attr_name,
        )

        user_group_in = UserGroupUpdate(id=user_group.id)
        setattr(user_group_in, relationship, items)

        user_group = await self.repo.update_user_group(user_group_in)

        # check all the relationships and raise exceptions if needed
        self._check_relationships(user_group)

        return user_group

    @validate_permissions(Permission.ADMIN)
    async def add_user(self, user_group_uuid: UUID, user_id: UUID) -> UserGroupInDB:
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return await self.append_items(
            user_group=user_group,
            relationship="users",
            item_uuid=user_id,
            attr_name="id",
        )

    @validate_permissions(Permission.ADMIN)
    async def remove_user(self, user_group_uuid: UUID, user_id: UUID) -> UserGroupInDB:
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return await self.pop_items(
            user_group=user_group,
            relationship="users",
            item_uuid=user_id,
            attr_name="id",
        )
