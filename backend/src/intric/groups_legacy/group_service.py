from typing import TYPE_CHECKING
from uuid import UUID

from intric.ai_models.ai_models_service import AIModelsService
from intric.groups_legacy.api.group_models import (
    CreateGroupRequest,
    CreateSpaceGroup,
    Group,
    GroupCreate,
    GroupUpdate,
    GroupUpdatePublic,
)
from intric.groups_legacy.group_repo import GroupRepository
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission, validate_permissions
from intric.spaces.space_service import SpaceService
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from tempfile import SpooledTemporaryFile

    from intric.actors import ActorManager
    from intric.jobs.task_service import TaskService
    from intric.spaces.space_repo import SpaceRepository


class GroupService:
    def __init__(
        self,
        user: UserInDB,
        repo: GroupRepository,
        space_repo: "SpaceRepository",
        tenant_repo: TenantRepository,
        info_blob_repo: InfoBlobRepository,
        ai_models_service: AIModelsService,
        space_service: SpaceService,
        actor_manager: "ActorManager",
        task_service: "TaskService",
    ):
        self.user = user
        self.repo = repo
        self.space_repo = space_repo
        self.tenant_repo = tenant_repo
        self.info_blob_repo = info_blob_repo
        self.ai_models_service = ai_models_service
        self.space_service = space_service
        self.actor_manager = actor_manager
        self.task_service = task_service

    async def check_space_embedding_model(self, group: Group):
        space = await self.space_service.get_space(group.space_id)

        if not space.is_embedding_model_in_space(group.embedding_model_id):
            raise BadRequestException(
                f"Space does not have embedding model {group.embedding_model.name} enabled."
            )

    async def _validate_embedding_model(self, group: GroupCreate | GroupUpdate):
        if group.embedding_model_id is not None:
            await self.ai_models_service.get_embedding_model(group.embedding_model_id)

    @validate_permissions(Permission.COLLECTIONS)
    async def create_group(self, group: CreateGroupRequest):
        group_create = GroupCreate(
            **group.model_dump(),
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
        )

        await self._validate_embedding_model(group_create)

        return await self.repo.create_group(group_create)

    async def create_space_group(
        self,
        name: str,
        space_id: UUID,
        embedding_model_id: UUID | None = None,
    ):
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_collections():
            raise UnauthorizedException()

        if embedding_model_id is None:
            if space.is_personal():
                embedding_model = await self.ai_models_service.get_latest_available_embedding_model()
            else:
                embedding_model = space.get_latest_embedding_model()
            if embedding_model is None:
                raise BadRequestException(
                    "Can not create a group in a space that does not have an embedding model enabled"
                )
            embedding_model_id = embedding_model.id
        elif not space.is_embedding_model_in_space(embedding_model_id):
            raise UnauthorizedException("Embedding model is not available in the space")

        group_create = CreateSpaceGroup(
            name=name,
            space_id=space_id,
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            embedding_model_id=embedding_model_id,
        )

        group = await self.repo.create_group(group_create)

        await self.repo.link_group_to_space(group_id=group.id, space_id=space_id)

        return group

    async def get_groups_for_user(self) -> list[Group]:
        return await self.repo.get_groups_by_user(self.user.id)

    async def get_group(self, group_id: UUID) -> Group:
        space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        group = space.get_collection(collection_id=group_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_collections():
            raise UnauthorizedException()

        return group

    async def get_groups_by_ids(self, ids: list[UUID]) -> list[Group]:
        groups = await self.repo.get_groups_by_ids(ids)

        for group in groups:
            space = await self.space_service.get_space(group.space_id)
            actor = self.actor_manager.get_space_actor_from_space(space)

            if not actor.can_read_collections():
                raise UnauthorizedException()

        return groups

    async def update_group(self, group_update: GroupUpdatePublic, group_id: UUID):
        space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_edit_collections():
            raise UnauthorizedException()

        group_update = GroupUpdate(**group_update.model_dump(exclude_unset=True), id=group_id)
        group_in_db = await self.repo.update_group(group_update)

        return group_in_db

    async def update_group_size(self, group_id: UUID):
        return await self.repo.update_group_size(group_id=group_id)

    async def add_file_to_group(
        self, group_id: UUID, file: "SpooledTemporaryFile", mimetype: str, filename: str
    ):
        space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        group = space.get_collection(collection_id=group_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        # Adding files to a group is considered editing the group
        if not actor.can_edit_collections():
            raise UnauthorizedException()

        if not space.is_embedding_model_in_space(group.embedding_model.id):
            raise BadRequestException(
                f"Space does not have embedding model {group.embedding_model.name} enabled."
            )

        return await self.task_service.queue_upload_file(
            group_id=group_id,
            space_id=space.id,
            file=file,
            mimetype=mimetype,
            filename=filename,
        )

    async def delete_group(self, group_id: UUID):
        space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        group = space.get_collection(collection_id=group_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_collections():
            raise UnauthorizedException()

        count = await self.get_count_for_group(group)

        group_in_db = await self.repo.delete_group_by_id(group.id)

        return group_in_db, count

    async def get_count_for_group(self, group: Group):
        return await self.info_blob_repo.get_count_of_group(group.id)

    async def get_counts_for_groups(self, groups: list[Group]):
        return [await self.get_count_for_group(group) for group in groups]

    async def move_group_owner_to_space(
        self,
        group_id: UUID,
        space_id: UUID,
        assistant_ids: list[UUID] = [],
        service_ids: list[UUID] = [],
    ):
        source_space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        group = source_space.get_collection(collection_id=group_id)
        source_actor = self.actor_manager.get_space_actor_from_space(source_space)
        target_space = await self.space_service.get_space(space_id)
        target_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not source_actor.can_delete_collections():
            raise UnauthorizedException("User does not have permissions to move group from space")
        if not target_actor.can_create_collections():
            raise UnauthorizedException("User does not have permission to create groups in the space")
        if not target_space.is_embedding_model_in_space(group.embedding_model.id):
            raise BadRequestException(
                f"Space does not have embedding model {group.embedding_model.name} enabled."
            )
        if source_space.id == space_id:
            return group

        group_in_db = await self.repo.move_group_owner(
            group_id=group_id, new_owner_space_id=space_id
        )

        await self.repo.unlink_group_from_all_spaces(group_id=group_id)
        await self.repo.link_group_to_space(group_id=group_id, space_id=space_id)

        await self.repo.remove_group_from_all_assistants(
            group_id=group_id, assistant_ids=assistant_ids
        )
        await self.repo.remove_group_from_all_services(group_id=group_id, service_ids=service_ids)

        return group_in_db

    async def get_groups_for_space(self, space_id: UUID) -> list[Group]:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_collections():
            raise UnauthorizedException()
        return await self.repo.get_groups_by_space(space_id)

    async def import_group_to_space(
        self,
        group_id: UUID,
        space_id: UUID,
    ):
        source_space = await self.space_repo.get_space_by_collection(collection_id=group_id)
        group = source_space.get_collection(collection_id=group_id)
        target_space = await self.space_service.get_space(space_id)

        source_actor = self.actor_manager.get_space_actor_from_space(source_space)
        target_actor = self.actor_manager.get_space_actor_from_space(target_space)
        if not source_actor.can_read_collections():
            raise UnauthorizedException("User cannot read group in source space")
        if not target_actor.can_create_collections():
            raise UnauthorizedException("User cannot import into target space")

        if not target_space.is_embedding_model_in_space(group.embedding_model.id):
            raise BadRequestException(
                f"Space does not have embedding model {group.embedding_model.name} enabled."
            )

        await self.repo.link_group_to_space(group_id=group_id, space_id=space_id)
