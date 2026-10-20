from typing import TYPE_CHECKING

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.widgets.domain.exceptions import AssistantPublishedAsWidgetError
from eneo.widgets.domain.widget import WidgetStatus

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.actors import ActorManager
    from eneo.assistants.assistant_repo import AssistantRepository
    from eneo.skills.domain.skill_repo import SkillRepo
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB
    from eneo.widgets.domain.widget_repo import WidgetRepo


class ResourceMoverService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        actor_manager: "ActorManager",
        skill_repo: "SkillRepo",
        widget_repo: "WidgetRepo",
        assistant_repo: "AssistantRepository",
    ):
        super().__init__()
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.skill_repo = skill_repo
        self.widget_repo = widget_repo
        self.assistant_repo = assistant_repo

    def _require_same_tenant(self, *spaces: "Space") -> None:
        """Moves never cross a tenant boundary.

        The caller, the source and the destination must all belong to one
        tenant. Space permissions are checked separately; this gate holds
        even for a principal that is privileged in both spaces.
        """
        for space in spaces:
            if space.tenant_id is None or space.tenant_id != self.user.tenant_id:
                raise UnauthorizedException("Resources cannot be moved between tenants")

    async def move_assistant_to_space(self, assistant_id: "UUID", space_id: "UUID"):
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
        # A widget serves its assistant from the widget's own space; moving
        # the assistant away would take a live widget offline without a word.
        # Drafts never served anyone and are archived with the move.
        widgets = await self.widget_repo.list_by_target(assistant_id)
        if any(widget.status is not WidgetStatus.DRAFT for widget in widgets):
            raise AssistantPublishedAsWidgetError()

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

        if enable_model and model is not None:
            await self.space_repo.enable_completion_model(space_id, model.id)
        await self.assistant_repo.move(assistant_id, locked_source_space_id, space_id)

        if widgets:
            from eneo.widgets.application.widget_target_lifecycle import (
                archive_drafts_of_moved_assistant,
            )

            await archive_drafts_of_moved_assistant(
                self.space_repo.session, drafts=widgets, user=self.actor_manager.user
            )
