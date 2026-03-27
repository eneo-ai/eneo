# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.prompts.prompt import Prompt
from eneo.prompts.prompt_factory import PromptFactory
from eneo.prompts.prompt_repo import PromptRepository
from eneo.users.user import UserInDB


class PromptService:
    def __init__(self, user: UserInDB, repo: PromptRepository, factory: PromptFactory):
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

    async def update_prompt_description(self, id: UUID, description: str) -> Prompt:
        prompt = await self.get_prompt(id)

        if prompt.user.id != self.user.id:
            raise UnauthorizedException("Prompt belongs to other user")

        return await self.repo.update_prompt_description(id=id, description=description)

    async def delete_prompt(self, id: UUID):
        prompt = await self.get_prompt(id)

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
