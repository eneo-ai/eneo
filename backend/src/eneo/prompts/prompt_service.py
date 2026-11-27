# Copyright (c) 2024 Sundsvalls Kommun


from uuid import UUID

from eneo.authentication.principal import Principal
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.prompts.prompt import Prompt
from eneo.prompts.prompt_factory import PromptFactory
from eneo.prompts.prompt_repo import PromptRepository
from eneo.users.user import UserInDB


def wrote_prompt(user: UserInDB, prompt: Prompt) -> bool:
    """Whether this principal wrote the prompt. Only its writer may change or
    remove it; a prompt with no writer left belongs to nobody."""
    principal = Principal.from_user(user)
    if principal.is_service_key:
        return prompt.created_by_service_id == principal.principal_service_id
    return prompt.user_id is not None and prompt.user_id == principal.principal_user_id


class PromptService:
    def __init__(
        self, user: UserInDB, repo: PromptRepository, factory: PromptFactory
    ) -> None:
        super().__init__()
        self.user = user
        self.repo = repo
        self.factory = factory

    async def get_prompt(self, id: UUID) -> Prompt:
        prompt = await self.repo.get(id)

        if prompt is None:
            raise NotFoundException()

        if prompt.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        return prompt

    async def create_prompt(
        self,
        text: str,
        description: str | None = None,
        owner_user_id: UUID | None = None,
    ):
        """Create a prompt.

        The prompt records who wrote it: the caller, a person or the service
        principal behind a service key. ``owner_user_id`` names a person
        instead: pass the owning resource's creator when the prompt is written
        as a child of an existing entity (an app's prompt being edited), so
        that person keeps the right to edit it.
        """
        creator = (
            Principal.from_user(self.user).creator_columns()
            if owner_user_id is None
            else {"user_id": owner_user_id, "created_by_service_id": None}
        )
        prompt = self.factory.create_prompt(
            text=text,
            description=description,
            user_id=creator["user_id"],
            created_by_service_id=creator["created_by_service_id"],
            tenant_id=self.user.tenant_id,
        )

        return await self.repo.add(prompt)

    async def update_prompt_description(
        self, id: UUID, description: str | None
    ) -> Prompt:
        prompt = await self.get_prompt(id)

        if not wrote_prompt(self.user, prompt):
            raise UnauthorizedException("Prompt belongs to other user")

        result = await self.repo.update_prompt_description(
            id=id, description=description
        )
        assert result is not None
        return result

    async def delete_prompt(self, id: UUID):
        prompt = await self.get_prompt(id)

        if not wrote_prompt(self.user, prompt):
            raise UnauthorizedException("Prompt belongs to other user")

        is_selected = await self.repo.is_selected(id)

        if is_selected:
            raise BadRequestException("You can not delete selected prompt.")

        await self.repo.delete_prompt(id)

    async def get_prompts_by_assistant(self, assistant_id: UUID):
        return await self.repo.get_prompts_by_assistant(assistant_id)

    async def get_prompts_by_app(self, app_id: UUID):
        return await self.repo.get_prompts_by_app(app_id=app_id)
