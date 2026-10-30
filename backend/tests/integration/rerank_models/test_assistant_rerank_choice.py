"""Choosing a reranker for an assistant, through the real service and database.

The choice is a nullable column on the assistant. It can be set to an enabled
rerank model, cleared again, and is refused for a model that is disabled.
"""

import pytest
from sqlalchemy import select

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import Assistants
from eneo.main.exceptions import BadRequestException

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _assistant_id(container):
    space = await container.space_init_service().get_personal_space()
    assert space.id is not None
    assistant, _ = await container.assistant_service().create_assistant(
        name="Chooses a reranker", space_id=space.id
    )
    return assistant.id


async def test_choose_and_clear_an_enabled_reranker(db_container, rerank_model_factory):
    async with db_container() as container:
        assistant_id = await _assistant_id(container)
        reranker = await rerank_model_factory(container.session(), "chosen")
        reranker_id = reranker.id

    async with db_container() as container:
        updated, _ = await container.assistant_service().update_assistant(
            assistant_id=assistant_id,
            update=AssistantUpdateCommand(rerank_model_id=reranker_id),
        )
        assert updated.rerank_model_id == reranker_id

    async with db_container() as container:
        stored = (
            await container.session().execute(
                select(Assistants.rerank_model_id).where(Assistants.id == assistant_id)
            )
        ).scalar_one()
        assert stored == reranker_id

        updated, _ = await container.assistant_service().update_assistant(
            assistant_id=assistant_id,
            update=AssistantUpdateCommand(rerank_model_id=None),
        )
        assert updated.rerank_model_id is None


async def test_a_disabled_reranker_cannot_be_chosen(db_container, rerank_model_factory):
    async with db_container() as container:
        assistant_id = await _assistant_id(container)
        disabled = await rerank_model_factory(
            container.session(), "disabled", is_enabled=False
        )
        disabled_id = disabled.id

    async with db_container() as container:
        with pytest.raises(BadRequestException, match="rerank model is not available"):
            await container.assistant_service().update_assistant(
                assistant_id=assistant_id,
                update=AssistantUpdateCommand(rerank_model_id=disabled_id),
            )
