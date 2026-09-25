# MIT License

from typing import TYPE_CHECKING
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
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
from eneo.users.user import UserInDB, UserInDBBase

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService


class UserGroupsService:
    def __init__(
        self,
        user: UserInDB,
        repo: UserGroupsRepository,
        audit_service: "AuditService",
    ):
        super().__init__()
        self.user = user
        self.repo = repo
        self.audit_service = audit_service

    async def _audit_membership_changes(
        self, before: UserGroupInDB, after: UserGroupInDB
    ) -> None:
        """Every user added to or removed from the group, always logged in
        the change's transaction: a group's role in a space gives its
        members that space's content, so this is how an access review sees
        who gained or lost access, and to which spaces."""
        old = {user.id: user for user in before.users}
        new = {user.id: user for user in after.users}
        changes = [
            (ActionType.USER_GROUP_MEMBER_ADDED, new[user_id])
            for user_id in new.keys() - old.keys()
        ] + [
            (ActionType.USER_GROUP_MEMBER_REMOVED, old[user_id])
            for user_id in old.keys() - new.keys()
        ]
        if not changes:
            return
        spaces = [
            {"id": str(space_id), "name": name, "role": role}
            for space_id, name, role in await self.repo.space_roles(
                after.id, self.user.tenant_id
            )
        ]
        for action, member in sorted(
            changes, key=lambda change: (change[0].value, str(change[1].id))
        ):
            await self._audit_member(action, after, member, spaces)

    async def _audit_member(
        self,
        action: ActionType,
        group: UserGroupInDB,
        member: UserInDBBase,
        spaces: list[dict[str, str]],
    ) -> None:
        name = member.username or member.email
        description = (
            f"Added {name} to user group '{group.name}'"
            if action == ActionType.USER_GROUP_MEMBER_ADDED
            else f"Removed {name} from user group '{group.name}'"
        )
        await self.audit_service.log_required(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.USER_GROUP,
            entity_id=group.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=group,
                extra={
                    "member": {
                        "id": str(member.id),
                        "name": name,
                        "email": member.email,
                    },
                    "spaces": spaces,
                },
            ),
        )

    def _validate(
        self, user_group: UserGroupInDB | None, user_group_uuid: UUID
    ) -> None:
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
        user_group_create = UserGroupCreate(
            name=user_group.name, tenant_id=self.user.tenant_id
        )
        return await self.repo.create_user_group(user_group_create)

    @validate_permissions(Permission.ADMIN)
    async def get_user_group_by_uuid(
        self, user_group_uuid: UUID
    ) -> UserGroupInDB | None:
        user_group = await self.repo.get_user_group(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return user_group

    @validate_permissions(Permission.ADMIN)
    async def update_user_group(
        self, user_group_update: UserGroupUpdateRequest, user_group_uuid: UUID
    ):
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)
        assert user_group is not None

        user_group_update = UserGroupUpdate(
            **user_group_update.model_dump(exclude_unset=True), id=user_group.id
        )
        updated_user_group = await self.repo.update_user_group(user_group_update)
        assert updated_user_group is not None

        # check all the relationships and raise exceptions if needed
        self._check_relationships(updated_user_group)
        await self._audit_membership_changes(user_group, updated_user_group)

        return updated_user_group

    @validate_permissions(Permission.ADMIN)
    async def delete_user_group(self, user_group_uuid: UUID):
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)

        return await self.repo.delete_user_group(user_group_uuid)

    async def get_all_user_groups(self):
        """List tenant user-groups for member/group pickers.

        Tenant-scoped at the repo layer. Exposes `UserSparse` per member
        (id, email, username) — no `quota_used`. Mutations (create/update/
        delete/add_user/remove_user) remain gated on Permission.ADMIN.
        """
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

        updated_user_group = await self.repo.update_user_group(user_group_in)
        assert updated_user_group is not None

        # check all the relationships and raise exceptions if needed
        self._check_relationships(updated_user_group)

        return updated_user_group

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
        attr_name: str = "uuid",
    ):
        items = self._pop_items_list(
            user_group=user_group,
            relationship=relationship,
            item_uuid=item_uuid,
            attr_name=attr_name,
        )

        user_group_in = UserGroupUpdate(id=user_group.id)
        setattr(user_group_in, relationship, items)

        updated_user_group = await self.repo.update_user_group(user_group_in)
        assert updated_user_group is not None

        # check all the relationships and raise exceptions if needed
        self._check_relationships(updated_user_group)

        return updated_user_group

    @validate_permissions(Permission.ADMIN)
    async def add_user(self, user_group_uuid: UUID, user_id: UUID) -> UserGroupInDB:
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)
        assert user_group is not None

        updated_user_group = await self.append_items(
            user_group=user_group,
            relationship="users",
            item_uuid=user_id,
            attr_name="id",
        )
        await self._audit_membership_changes(user_group, updated_user_group)
        return updated_user_group

    @validate_permissions(Permission.ADMIN)
    async def remove_user(self, user_group_uuid: UUID, user_id: UUID) -> UserGroupInDB:
        user_group = await self.get_user_group_by_uuid(user_group_uuid)
        self._validate(user_group, user_group_uuid)
        assert user_group is not None

        updated_user_group = await self.pop_items(
            user_group=user_group,
            relationship="users",
            item_uuid=user_id,
            attr_name="id",
        )
        await self._audit_membership_changes(user_group, updated_user_group)
        return updated_user_group
