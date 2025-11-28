from typing import TYPE_CHECKING, Optional

from intric.collections.domain.collection import Collection
from intric.main.exceptions import UnauthorizedException
from uuid import UUID

if TYPE_CHECKING:
    from intric.actors.actor_manager import ActorManager
    from intric.spaces.space_repo import SpaceRepository
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB
    from intric.groups_legacy.group_service import GroupService


class CollectionCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        actor_manager: "ActorManager",
        group_service: "GroupService",
    ):
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.group_service = group_service

    async def create_collection(
        self,
        space_id: "UUID",
        name: str,
        embedding_model_id: Optional["UUID"] = None,
    ) -> Collection:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_create_collections():
            raise UnauthorizedException()

        grp = await self.group_service.create_space_group(
            name=name,
            space_id=space.id,
            embedding_model_id=embedding_model_id,
        )

        space_after = await self.space_service.get_space_by_collection(group_id=grp.id)
        return space_after.get_collection(collection_id=grp.id)
    
    async def get_collection(self, collection_id: "UUID") -> Collection:
        space = await self.space_service.get_space_by_collection(collection_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_read_collections():
            raise UnauthorizedException()
        return space.get_collection(collection_id=collection_id)
    
    async def update_collection(
        self,
        collection_id: "UUID",
        name: str,
    ) -> Collection:
        space = await self.space_service.get_space_by_collection(collection_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_edit_collections():
            raise UnauthorizedException()

        collection = space.get_collection(collection_id=collection_id)
        collection.update(name=name)

        updated_space = await self.space_repo.update(space=space)
        return updated_space.get_collection(collection_id=collection_id)

    async def delete_collection(self, collection_id: "UUID") -> None:
        space = await self.space_service.get_space_by_collection(collection_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_delete_collections():
            raise UnauthorizedException()

        collection = space.get_collection(collection_id=collection_id)
        space.remove_collection(collection)
        await self.space_repo.update(space=space)