"""Creating a flow assistant while another transaction edits an assistant of the
same space must not wait for that edit. Creating an assistant used to rewrite
every assistant row of the space, so it waited on any row an edit held, and an
apply editing its assistants one by one deadlocked with it (me_int04,
2026-09-27)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import Assistants
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
    _flow_with_assistants,
    _names,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_an_assistant_does_not_wait_for_an_open_edit(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, [edited_id] = await _flow_with_assistants(
        db_container, space_id=space_id, names=["one"]
    )

    async def create_in_same_space() -> UUID:
        async with db_container() as container:
            assistant, _ = await container.flow_service().create_flow_assistant(
                flow_id=flow_id, name="created meanwhile"
            )
            return assistant.id

    async with db_container() as editing:
        await editing.flow_service().update_flow_assistant(
            flow_id=flow_id,
            assistant_id=edited_id,
            update=AssistantUpdateCommand(name="edited"),
        )
        # The edit holds its row until this block commits.
        created_id = await asyncio.wait_for(create_in_same_space(), timeout=15)

    assert await _names(db_container, [edited_id, created_id]) == {
        edited_id: "edited",
        created_id: "created meanwhile",
    }
    async with db_container() as container:
        created_space_id = await container.session().scalar(
            sa.select(Assistants.space_id).where(Assistants.id == created_id)
        )
    assert created_space_id == space_id
