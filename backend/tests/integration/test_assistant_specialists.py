"""Persisted contract for an assistant's specialists."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.assistants.assistant_update import AssistantUpdate
from eneo.database.tables.assistant_table import Assistants, AssistantSpecialists


async def _links(session, assistant_id):
    rows = await session.execute(
        sa.select(
            AssistantSpecialists.specialist_id, AssistantSpecialists.description
        ).where(AssistantSpecialists.assistant_id == assistant_id)
    )
    return {specialist_id: description for specialist_id, description in rows}


async def test_specialists_are_stored_replaced_and_loaded_with_the_space(
    db_container, admin_user, space_factory, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        space = await space_factory(session, "Source", [model.id])
        lead = await assistant_factory(session, "Lead", model.id, space_id=space.id)
        hr = await assistant_factory(
            session, "HR", model.id, space_id=space.id, description="Leave and pay"
        )
        it = await assistant_factory(session, "IT", model.id, space_id=space.id)
        space_id, lead_id, hr_id, it_id = space.id, lead.id, hr.id, it.id

    async with db_container() as container:
        repo = container.assistant_repo()
        await repo.apply_update(
            lead_id,
            space_id,
            AssistantUpdate(specialists={hr_id: None, it_id: "Accounts and access"}),
        )

    async with db_container() as container:
        session = container.session()
        assert await _links(session, lead_id) == {
            hr_id: None,
            it_id: "Accounts and access",
        }
        loaded = await container.space_repo().get_space_by_assistant(
            assistant_id=lead_id
        )
        specialists = {
            specialist.id: specialist
            for specialist in loaded.get_assistant(lead_id).specialists
        }
        assert specialists[hr_id].description == "Leave and pay"
        assert specialists[it_id].description == "Accounts and access"
        assert loaded.get_assistant(hr_id).specialists == []

    # The list replaces; an empty list clears.
    async with db_container() as container:
        repo = container.assistant_repo()
        await repo.apply_update(
            lead_id, space_id, AssistantUpdate(specialists={hr_id: "Only HR"})
        )
    async with db_container() as container:
        assert await _links(container.session(), lead_id) == {hr_id: "Only HR"}
    async with db_container() as container:
        await container.assistant_repo().apply_update(
            lead_id, space_id, AssistantUpdate(specialists={})
        )
    async with db_container() as container:
        assert await _links(container.session(), lead_id) == {}


async def test_self_reference_is_rejected_by_the_database(
    db_container, space_factory, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        space = await space_factory(session, "Source", [model.id])
        lead = await assistant_factory(session, "Lead", model.id, space_id=space.id)
        lead_id = lead.id
    async with db_container() as container:
        session = container.session()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    sa.insert(AssistantSpecialists).values(
                        assistant_id=lead_id, specialist_id=lead_id
                    )
                )


async def test_links_follow_deletion_and_are_dropped_on_move(
    db_container, space_factory, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        source = await space_factory(session, "Source", [model.id])
        target = await space_factory(session, "Target", [model.id])
        lead = await assistant_factory(session, "Lead", model.id, space_id=source.id)
        hr = await assistant_factory(session, "HR", model.id, space_id=source.id)
        it = await assistant_factory(session, "IT", model.id, space_id=source.id)
        source_id, target_id = source.id, target.id
        lead_id, hr_id, it_id = lead.id, hr.id, it.id
    async with db_container() as container:
        repo = container.assistant_repo()
        await repo.apply_update(
            lead_id, source_id, AssistantUpdate(specialists={hr_id: None, it_id: None})
        )
        await repo.apply_update(
            it_id, source_id, AssistantUpdate(specialists={hr_id: None})
        )

    # Deleting a specialist removes every link to it; the orchestrator keeps the rest.
    async with db_container() as container:
        await container.assistant_repo().delete(hr_id, source_id)
    async with db_container() as container:
        session = container.session()
        assert await _links(session, lead_id) == {it_id: None}
        assert await _links(session, it_id) == {}

    # Moving an assistant to another space drops its links in both directions.
    async with db_container() as container:
        await container.assistant_repo().move(it_id, source_id, target_id)
    async with db_container() as container:
        session = container.session()
        assert await _links(session, lead_id) == {}
        assert (
            await session.scalar(
                sa.select(Assistants.space_id).where(Assistants.id == it_id)
            )
            == target_id
        )
