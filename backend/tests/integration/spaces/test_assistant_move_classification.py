"""Moving an assistant into a classified space brings its model along, so the
model has to meet the space's level."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces, SpacesCompletionModels
from eneo.database.tables.tenant_table import Tenants
from eneo.main.exceptions import BadRequestException


async def _prepare(
    db_container,
    admin_user,
    assistant_factory,
    completion_model_factory,
    *,
    model_level: int,
):
    """An assistant in a source space, and a target space at level 2 that does not
    yet offer the assistant's model."""
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=True)
        )
        levels = {}
        for level in (model_level, 2):
            if level not in levels:
                row = SecurityClassification(
                    name=f"level-{level}-{uuid4().hex[:6]}",
                    security_level=level,
                    tenant_id=admin_user.tenant_id,
                )
                session.add(row)
                await session.flush()
                levels[level] = row.id
        source = await container.space_init_service().create_space("Source")
        target = await container.space_init_service().create_space("Target")
        model = await completion_model_factory(
            session, "Moved model", security_classification_id=levels[model_level]
        )
        assistant = await assistant_factory(
            session, "Moved assistant", model.id, space_id=source.id
        )
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == target.id)
            .values(security_classification_id=levels[2])
        )
        await session.execute(
            sa.delete(SpacesCompletionModels).where(
                SpacesCompletionModels.space_id == target.id,
                SpacesCompletionModels.completion_model_id == model.id,
            )
        )
        return {
            "assistant_id": assistant.id,
            "source_id": source.id,
            "target_id": target.id,
            "model_id": model.id,
        }


async def _link_exists(db_container, ids) -> bool:
    async with db_container() as container:
        return bool(
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(SpacesCompletionModels)
                .where(
                    SpacesCompletionModels.space_id == ids["target_id"],
                    SpacesCompletionModels.completion_model_id == ids["model_id"],
                )
            )
        )


async def _space_of(db_container, assistant_id):
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Assistants.space_id).where(Assistants.id == assistant_id)
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_assistant_with_a_model_below_the_target_level_is_not_moved(
    db_container, admin_user, assistant_factory, completion_model_factory
):
    ids = await _prepare(
        db_container,
        admin_user,
        assistant_factory,
        completion_model_factory,
        model_level=1,
    )

    with pytest.raises(BadRequestException):
        async with db_container() as container:
            await container.resource_mover_service().move_assistant_to_space(
                ids["assistant_id"], ids["target_id"]
            )

    assert not await _link_exists(db_container, ids)
    assert await _space_of(db_container, ids["assistant_id"]) == ids["source_id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_assistant_with_a_model_that_meets_the_target_level_is_moved(
    db_container, admin_user, assistant_factory, completion_model_factory
):
    ids = await _prepare(
        db_container,
        admin_user,
        assistant_factory,
        completion_model_factory,
        model_level=2,
    )

    async with db_container() as container:
        await container.resource_mover_service().move_assistant_to_space(
            ids["assistant_id"], ids["target_id"]
        )

    assert await _link_exists(db_container, ids)
    assert await _space_of(db_container, ids["assistant_id"]) == ids["target_id"]
