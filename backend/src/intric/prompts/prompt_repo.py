# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.tables.app_table import AppsPrompts
from intric.database.tables.prompts_table import Prompts, PromptsAssistants
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_factory import PromptFactory


class PromptRepository:
    def __init__(self, session: AsyncSession, factory: PromptFactory) -> None:
        super().__init__()
        self.session = session
        self.factory = factory

    def _to_domain(
        self, prompt_in_db: Prompts | None, is_selected: bool | None
    ) -> Prompt | None:
        if prompt_in_db is None:
            return None

        return self.factory.create_prompt_from_db(prompt_in_db, is_selected=is_selected)

    async def is_selected(self, prompt_id: UUID):
        stmt = sa.select(PromptsAssistants.is_selected).where(
            PromptsAssistants.prompt_id == prompt_id
        )

        return await self.session.scalar(stmt)

    async def get_prompts_by_assistant(self, assistant_id: UUID) -> list[Prompt]:
        stmt = (
            sa.select(Prompts, PromptsAssistants)
            .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
            .where(PromptsAssistants.assistant_id == assistant_id)
            .order_by(Prompts.created_at.desc())
            .options(selectinload(Prompts.user))
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            p
            for row in rows
            if (p := self._to_domain(row[0], row[1].is_selected)) is not None
        ]

    async def get_prompts_by_app(self, app_id: UUID) -> list[Prompt]:
        stmt = (
            sa.select(Prompts, AppsPrompts)
            .join(AppsPrompts, AppsPrompts.prompt_id == Prompts.id)
            .where(AppsPrompts.app_id == app_id)
            .order_by(Prompts.created_at.desc())
            .options(selectinload(Prompts.user))
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            p
            for row in rows
            if (p := self._to_domain(row[0], row[1].is_selected)) is not None
        ]

    async def get(self, id: UUID) -> Prompt | None:
        stmt = (
            sa.select(Prompts)
            .where(Prompts.id == id)
            .options(selectinload(Prompts.user))
        )

        prompt_in_db = await self.session.scalar(stmt)

        if prompt_in_db is None:
            return None

        return self.factory.create_prompt_from_db(prompt_in_db=prompt_in_db)

    async def add(self, prompt: Prompt) -> Prompt | None:
        stmt = (
            sa.insert(Prompts)
            .values(
                text=prompt.text,
                description=prompt.description,
                user_id=prompt.user_id,
                tenant_id=prompt.tenant_id,
            )
            .returning(Prompts)
            .options(selectinload(Prompts.user))
        )

        prompt_in_db = await self.session.scalar(stmt)
        assert prompt_in_db is not None

        return self.factory.create_prompt_from_db(prompt_in_db=prompt_in_db)

    async def update_prompt_description(
        self, id: UUID, description: str | None
    ) -> Prompt | None:
        stmt = (
            sa.update(Prompts)
            .values(description=description)
            .where(Prompts.id == id)
            .returning(Prompts)
            .options(selectinload(Prompts.user))
        )

        updated_prompt = await self.session.scalar(stmt)

        is_selected = await self.is_selected(id)

        return self._to_domain(updated_prompt, is_selected)

    async def delete_prompt(self, id: UUID) -> None:
        query = sa.delete(Prompts).where(Prompts.id == id)
        await self.session.execute(query)
