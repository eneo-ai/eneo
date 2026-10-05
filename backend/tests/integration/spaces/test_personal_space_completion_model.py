"""The personal assistant always points at a usable completion model once the
organisation has one. Regression test for personal chats created before any
model existed, which stayed model-less forever and showed "no AI model
available" even after an admin enabled models."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants


async def _remove_all_completion_models(session, tenant_id) -> None:
    await session.execute(
        sa.delete(CompletionModels).where(
            sa.or_(
                CompletionModels.tenant_id == tenant_id,
                CompletionModels.tenant_id.is_(None),
            )
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_assistant_gets_a_model_once_one_exists(
    db_container, admin_user, completion_model_factory
):
    async with db_container() as container:
        await _remove_all_completion_models(container.session(), admin_user.tenant_id)
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.completion_model is None
        assistant_id = assistant.id

    async with db_container() as container:
        model = await completion_model_factory(
            container.session(), "late-model", is_default=True
        )
        model_id = model.id

    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.id == assistant_id
        assert assistant.completion_model is not None
        assert assistant.completion_model.id == model_id

        row = await container.session().get(Assistants, assistant_id)
        assert row is not None
        assert row.completion_model_id == model_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_assistant_keeps_its_model_when_it_is_usable(
    db_container, admin_user, completion_model_factory
):
    async with db_container() as container:
        other = await completion_model_factory(container.session(), "chosen-model")
        other_id = other.id

    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.completion_model is not None
        assert assistant.completion_model.id != other_id
        assistant_id = assistant.id
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(completion_model_id=other_id)
        )

    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.completion_model is not None
        assert assistant.completion_model.id == other_id
