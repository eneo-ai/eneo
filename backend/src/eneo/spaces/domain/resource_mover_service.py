from typing import TYPE_CHECKING

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.actors import ActorManager
    from eneo.assistants.assistant_repo import AssistantRepository
    from eneo.groups_legacy.group_service import GroupService
    from eneo.skills.domain.skill_repo import SkillRepo
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB
    from eneo.websites.infrastructure.website_repo import WebsiteRepository


class ResourceMoverService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        actor_manager: "ActorManager",
        group_service: "GroupService",
        skill_repo: "SkillRepo",
        assistant_repo: "AssistantRepository",
        website_repo: "WebsiteRepository",
    ):
        super().__init__()
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.group_service = group_service
        self.skill_repo = skill_repo
        self.assistant_repo = assistant_repo
        self.website_repo = website_repo

    def _require_same_tenant(self, *spaces: "Space") -> None:
        """Moves and links never cross a tenant boundary.

        The caller, the source and the destination must all belong to one
        tenant. Space permissions are checked separately; this gate holds
        even for a principal that is privileged in both spaces.
        """
        for space in spaces:
            if space.tenant_id is None or space.tenant_id != self.user.tenant_id:
                raise UnauthorizedException("Resources cannot be moved between tenants")

    def _require_resources_in_tenant(self, *tenant_ids: "UUID") -> None:
        """Attached collections and websites must belong to the caller's tenant."""
        for tenant_id in tenant_ids:
            if tenant_id != self.user.tenant_id:
                raise UnauthorizedException("Resources cannot be moved between tenants")

    async def link_website_to_space(self, website_id: "UUID", space_id: "UUID"):
        source_space = await self.space_service.get_space_by_website(website_id)
        source_actor = self.actor_manager.get_space_actor_from_space(source_space)

        if not getattr(source_actor, "can_read_websites", lambda: False)():
            raise UnauthorizedException("User cannot read websites in the source space")

        target_space = await self.space_service.get_space(space_id)
        target_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not target_actor.can_create_websites():
            raise UnauthorizedException(
                "User cannot create websites in the target space"
            )

        self._require_same_tenant(source_space, target_space)
        website = source_space.get_website(website_id)
        self._require_resources_in_tenant(website.tenant_id)

        if website.id not in [w.id for w in target_space.websites]:
            target_space.add_website(website)

        await self.website_repo.link(website_id, space_id)

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

        self._require_same_tenant(source_space, target_space)
        collection = source_space.get_collection(collection_id)
        self._require_resources_in_tenant(collection.tenant_id)

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

        self._require_same_tenant(source_space, target_space)

        assert source_space.id is not None and target_space.id is not None
        if source_space.id == target_space.id:
            raise BadRequestException("Assistant is already in the space")
        # Lock parents in stable order before the assistant, then re-read access
        # facts. Membership and settings writes take the same parent lock.
        for locked_id in sorted({source_space.id, target_space.id}, key=str):
            await self.space_repo.lock(locked_id)
        target_space = await self.space_service.get_space(space_id)
        target_space_actor = self.actor_manager.get_space_actor_from_space(target_space)
        if not target_space_actor.can_create_assistants():
            raise UnauthorizedException(
                "User cannot create assistants in the target space"
            )

        locked_source_space_id = await self.skill_repo.lock_assistant_space_for_update(
            assistant_id=assistant_id
        )
        if locked_source_space_id is None:
            raise NotFoundException()

        if locked_source_space_id != source_space.id:
            raise BadRequestException(
                "Assistant moved concurrently; reload before retrying"
            )
        source_space = await self.space_service.get_space(locked_source_space_id)
        source_space_actor = self.actor_manager.get_space_actor_from_space(source_space)
        if not source_space_actor.can_delete_assistants():
            raise UnauthorizedException(
                "User does not have permission to move assistant from space"
            )
        self._require_same_tenant(source_space, target_space)

        assistant = source_space.get_assistant(assistant_id)

        if await self.skill_repo.has_assistant_bindings(assistant_id=assistant_id):
            raise BadRequestException(
                "Remove the Assistant's Skill bindings before moving it to another Space"
            )

        if move_resources:
            self._require_resources_in_tenant(
                *(collection.tenant_id for collection in assistant.collections),
                *(website.tenant_id for website in assistant.websites),
            )

        if assistant.is_default:
            raise BadRequestException(
                "The default assistant cannot move between spaces"
            )
        model = assistant.completion_model
        enable_model = (
            model is not None
            and not target_space.is_completion_model_in_space(model.id)
        )
        target_space.add_assistant(assistant)

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

                assert target_space.id is not None
                await self.group_service.import_group_to_space(
                    group_id=collection.id,
                    space_id=target_space.id,
                )

            for website in assistant.websites:
                if not getattr(
                    source_space_actor, "can_read_websites", lambda: False
                )():
                    raise UnauthorizedException(
                        "User cannot read websites in source space"
                    )
                if not target_space_actor.can_create_websites():
                    raise UnauthorizedException(
                        "User cannot create websites in target space"
                    )

                if website.id not in [w.id for w in target_space.websites]:
                    target_space.add_website(website)
                await self.website_repo.link(website.id, space_id)

        if enable_model and model is not None:
            await self.space_repo.enable_completion_model(space_id, model.id)
        await self.assistant_repo.move(assistant_id, locked_source_space_id, space_id)
