from typing import TYPE_CHECKING

from intric.main.exceptions import UnauthorizedException

if TYPE_CHECKING:
    from uuid import UUID

    from intric.actors import ActorManager
    from intric.spaces.space_repo import SpaceRepository
    from intric.spaces.space_service import SpaceService
    from intric.groups_legacy.group_service import GroupService

class ResourceMoverService:
    def __init__(
        self,
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        actor_manager: "ActorManager",
        group_service: "GroupService"
    ):
        self.space_service = space_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.group_service = group_service


    async def link_website_to_space(self, website_id: "UUID", space_id: "UUID"):
        source_space = await self.space_service.get_space_by_website(website_id)
        source_actor = self.actor_manager.get_space_actor_from_space(source_space)

        if not getattr(source_actor, "can_read_websites", lambda: False)():
            raise UnauthorizedException("User cannot read websites in the source space")

        target_space = await self.space_service.get_space(space_id)
        target_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not target_actor.can_create_websites():
            raise UnauthorizedException("User cannot create websites in the target space")

        website = source_space.get_website(website_id)

        if website.id not in [w.id for w in target_space.websites]:
            target_space.add_website(website)

        await self.space_repo.update(space=target_space)

    async def move_website_to_space(self, website_id: "UUID", space_id: "UUID"):
        """
        Flyttar websiten (med unlink från källan) - ändrar INTE owner i den här versionen.
        Rekommenderas att använda link_website_to_space istället.
        """
        source_space = await self.space_service.get_space_by_website(website_id)
        source_actor = self.actor_manager.get_space_actor_from_space(source_space)

        if not source_actor.can_delete_websites():
            raise UnauthorizedException("User does not have permission to move website from space")

        target_space = await self.space_service.get_space(space_id)
        target_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not target_actor.can_create_websites():
            raise UnauthorizedException("User does not have permission to create websites in the space")

        website = source_space.get_website(website_id)

        if website.id not in [w.id for w in target_space.websites]:
            target_space.add_website(website)

        if website in source_space.websites:
            source_space.remove_website(website)

        await self.space_repo.update(space=target_space)
        await self.space_repo.update(space=source_space)


    async def move_collection_to_space(self, collection_id: "UUID", space_id: "UUID"):
        source_space = await self.space_service.get_space_by_collection(collection_id)
        source_space_actor = self.actor_manager.get_space_actor_from_space(source_space)

        if not source_space_actor.can_delete_collections():
            raise UnauthorizedException(
                "User does not have permission to move collection from space"
            )

        target_space = await self.space_service.get_space(space_id)
        target_space_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not target_space_actor.can_create_collections():
            raise UnauthorizedException(
                "User does not have permission to create collections in the space"
            )

        await self.group_service.import_group_to_space(
            group_id=collection_id,
            space_id=space_id,
        )

   
    async def move_assistant_to_space(
        self, assistant_id: "UUID", space_id: "UUID", move_resources: bool = False
    ):
        """
        Flytta en assistant mellan spaces. Om move_resources=True:
        - Importera (länka) alla collections till mål-space (behåll ägarskap)
        """
        source_space = await self.space_service.get_space_by_assistant(assistant_id)
        source_space_actor = self.actor_manager.get_space_actor_from_space(source_space)

        if not source_space_actor.can_delete_assistants():
            raise UnauthorizedException(
                "User does not have permission to move assistant from space"
            )

        target_space = await self.space_service.get_space(space_id)
        target_space_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not target_space_actor.can_create_assistants():
            raise UnauthorizedException(
                "User does not have permission to create assistants in the space"
            )

        assistant = source_space.get_assistant(assistant_id)

        target_space.add_assistant(assistant)
        source_space.remove_assistant(assistant)

        if move_resources:
            for collection in assistant.collections:
                if not source_space_actor.can_read_collections():
                    raise UnauthorizedException(
                        "User cannot read group in source space"
                    )
                if not target_space_actor.can_create_collections():
                    raise UnauthorizedException(
                        "User cannot import collections into target space"
                    )

                await self.group_service.import_group_to_space(
                    group_id=collection.id,
                    space_id=target_space.id,
                )

            for website in assistant.websites:
                if not getattr(source_space_actor, "can_read_websites", lambda: False)():
                    raise UnauthorizedException("User cannot read websites in source space")
                if not target_space_actor.can_create_websites():
                    raise UnauthorizedException("User cannot create websites in target space")

                if website.id not in [w.id for w in target_space.websites]:
                    target_space.add_website(website)

        await self.space_repo.update(space=target_space)
        await self.space_repo.update(space=source_space)