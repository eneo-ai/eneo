# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from eneo.database.tables.prompts_table import Prompts
from eneo.prompts.prompt import Prompt


class PromptFactory:
    @staticmethod
    def create_prompt(
        text: str | None,
        description: str | None,
        user_id: UUID,
        tenant_id: UUID,
    ) -> Prompt:
        return Prompt(
            created_at=None,
            updated_at=None,
            id=None,
            description=description,
            text=text,  # type: ignore[arg-type]  # text may be None; Prompt.text: str but dataclass allows None for new (unsaved) prompts
            is_selected=True,
            user=None,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    @staticmethod
    def create_prompt_from_db(
        prompt_in_db: Prompts, is_selected: bool | None = None
    ) -> Prompt:
        return Prompt(
            created_at=prompt_in_db.created_at,
            updated_at=prompt_in_db.updated_at,
            id=prompt_in_db.id,
            description=prompt_in_db.description,
            text=prompt_in_db.text,
            is_selected=is_selected,
            user=prompt_in_db.user,  # type: ignore[arg-type]  # Users ORM object satisfies UserSparse at runtime via Pydantic from_orm
            tenant_id=prompt_in_db.tenant_id,
            user_id=prompt_in_db.user_id,
        )
