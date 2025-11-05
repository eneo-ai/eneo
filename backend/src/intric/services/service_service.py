from typing import TYPE_CHECKING
from uuid import UUID

from intric.groups_legacy.group_service import GroupService
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.questions.questions_repo import QuestionRepository
from intric.roles.permissions import Permission, validate_permissions
from intric.services.output_parsing.pydantic_model_factory import PydanticModelFactory
from intric.services.service import (
    CreateSpaceService,
    Service,
    ServiceBase,
    ServiceCreate,
    ServiceCreatePublic,
    ServiceUpdate,
    ServiceUpdatePublic,
)
from intric.services.service_repo import ServiceRepository
from intric.spaces.space_service import SpaceService
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.completion_models.application import CompletionModelCRUDService
    from intric.spaces.space import Space
    from intric.spaces.space_repo import SpaceRepository


class ServiceService:
    def __init__(
        self,
        repo: ServiceRepository,
        space_repo: "SpaceRepository",
        question_repo: QuestionRepository,
        group_service: GroupService,
        user: UserInDB,
        completion_model_crud_service: "CompletionModelCRUDService",
        space_service: SpaceService,
        actor_manager: "ActorManager",
    ):
        self.repo = repo
        self.space_repo = space_repo
        self.question_repo = question_repo
        self.group_service = group_service
        self.user = user
        self.space_service = space_service
        self.completion_model_crud_service = completion_model_crud_service
        self.actor_manager = actor_manager

    async def _validate(self, service: ServiceBase):
        if service.json_schema is not None:
            PydanticModelFactory(service.json_schema).validate_schema()

        if service.completion_model_id is not None:
            await self.completion_model_crud_service.get_completion_model(
                service.completion_model_id
            )

    async def _validate_same_embedding_model(self, service: ServiceCreate | ServiceUpdate):
        if not service.groups:
            return

        embedding_model_ids = set()
        if service.groups:
            groups_in_db = await self.group_service.get_groups_by_ids(
                [group.id for group in service.groups]
            )

            embedding_model_ids.update([group.embedding_model_id for group in groups_in_db])

        if len(embedding_model_ids) > 1:
            raise BadRequestException("All groups must have the same embedding model")

    async def validate_space_service(self, service: Service, space: "Space"):
        # validate completion mode
        if service.completion_model_id is not None:
            if not space.is_completion_model_in_space(service.completion_model_id):
                raise BadRequestException("Completion model is not in space.")

        # validate groups
        for group in service.groups:
            if not space.is_group_in_space(group.id):
                raise BadRequestException("Group is not in space.")

        await self._validate_same_embedding_model(service)

    @validate_permissions(Permission.SERVICES)
    async def create_service(self, service: ServiceCreatePublic):
        service_create = ServiceCreate(**service.model_dump(), user_id=self.user.id)

        await self._validate(service_create)
        await self._validate_same_embedding_model(service_create)

        return await self.repo.add(service_create)

    async def create_space_service(self, name: str, space_id: UUID):
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_create_services():
            raise UnauthorizedException(
                "User does not have permission to create services in this space"
            )

        completion_model = space.get_default_completion_model()

        if completion_model is None:
            raise BadRequestException(
                "Can not create an service in a space without enabled completion models"
            )

        service_create = CreateSpaceService(
            name=name,
            prompt="",
            user_id=self.user.id,
            space_id=space_id,
            completion_model_id=completion_model.id,
        )

        service_in_db = await self.repo.add(service_create)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return service_in_db, permissions

    async def update_service(self, service_update_pub: ServiceUpdatePublic, service_id: UUID):
        space = await self.space_repo.get_space_by_service(service_id=service_id)
        service_in_db = space.get_service(service_id=service_id)

        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_services():
            raise UnauthorizedException()

        service_update = ServiceUpdate(
            **service_update_pub.model_dump(exclude_unset=True),
            id=service_id,
        )

        await self._validate(service_update)
        await self._validate_same_embedding_model(service_update)

        service_in_db = await self.repo.update(service_update)

        await self.validate_space_service(service_in_db, space=space)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return service_in_db, permissions

    async def get_service(self, service_id: UUID):
        space = await self.space_repo.get_space_by_service(service_id=service_id)
        service = space.get_service(service_id=service_id)

        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_services():
            raise UnauthorizedException()

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return service, permissions

    async def get_services(self, name: str):
        return await self.repo.get_for_user(self.user.id, search_query=name)

    async def delete_service(self, service_id: UUID):
        space = await self.space_repo.get_space_by_service(service_id=service_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_services():
            raise UnauthorizedException()

        await self.repo.delete(service_id)

    async def get_service_runs(self, service_id: str):
        space = await self.space_repo.get_space_by_service(service_id=service_id)
        service = space.get_service(service_id=service_id)

        # Reading runs is determined by if the user can read the service
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_services():
            raise UnauthorizedException()

        runs = await self.question_repo.get_by_service(service.id)
        return service, runs

    async def move_service_to_space(self, service_id: UUID, space_id: UUID, move_resources: bool):
        source_space = await self.space_repo.get_space_by_service(service_id=service_id)
        service = source_space.get_service(service_id)

        target_space = await self.space_service.get_space(space_id)
        source_space_actor = self.actor_manager.get_space_actor_from_space(source_space)
        target_space_actor = self.actor_manager.get_space_actor_from_space(target_space)

        if not source_space_actor.can_delete_services():
            raise UnauthorizedException("User does not have permission to move service from space")

        if not target_space_actor.can_create_services():
            raise UnauthorizedException(
                "User does not have permission to create service in the space"
            )

        if not target_space.is_completion_model_in_space(service.completion_model.id):
            raise BadRequestException(
                f"Space does not have completion model {service.completion_model.name} enabled"
            )

        await self.repo.add_service_to_space(service_id=service_id, space_id=space_id)

        if move_resources:
            for group in service.groups:
                await self.group_service.import_group_to_space(
                    group_id=group.id,
                    space_id=space_id,
                )
