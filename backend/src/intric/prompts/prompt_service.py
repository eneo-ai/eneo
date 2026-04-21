# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_factory import PromptFactory
from intric.prompts.prompt_repo import PromptRepository
from intric.users.user import UserInDB


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

    async def create_prompt(self, text: str, description: str | None = None):
        prompt = self.factory.create_prompt(
            text=text,
            description=description,
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
        )

        return await self.repo.add(prompt)

    async def update_prompt_description(
        self, id: UUID, description: str | None
    ) -> Prompt:
        prompt = await self.get_prompt(id)
        assert prompt.user is not None

        if prompt.user.id != self.user.id:
            raise UnauthorizedException("Prompt belongs to other user")

        result = await self.repo.update_prompt_description(
            id=id, description=description
        )
        assert result is not None
        return result

    async def delete_prompt(self, id: UUID):
        prompt = await self.get_prompt(id)
        assert prompt.user is not None

        if prompt.user.id != self.user.id:
            raise UnauthorizedException("Prompt belongs to other user")

        is_selected = await self.repo.is_selected(id)

        if is_selected:
            raise BadRequestException("You can not delete selected prompt.")

        await self.repo.delete_prompt(id)

    async def get_prompts_by_assistant(self, assistant_id: UUID):
        return await self.repo.get_prompts_by_assistant(assistant_id)

    async def get_prompts_by_app(self, app_id: UUID):
        return await self.repo.get_prompts_by_app(app_id=app_id)
