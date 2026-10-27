"""A migrated real database admits saved and published deterministic JSON steps."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from eneo.database.tables.flow_tables import FlowSteps, FlowVersions
from eneo.flows.domain.flow import FlowStep
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_migrated_postgres_saves_and_publishes_copy_input_and_guards_rollback(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    test_settings,
):
    # Kills a missing live constraint, save/publish model requirement, dropped
    # snapshot vocabulary, or a downgrade that silently leaves copy drafts usable.
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Copy JSON",
            description=None,
        )
        assistant, _ = await service.create_flow_assistant(flow_id=flow.id, name="copy")
        step = FlowStep(
            assistant_id=assistant.id,
            step_order=1,
            input_source="flow_input",
            input_type="json",
            output_type="json",
            output_mode="copy_input",
            output_contract={"type": "object"},
        )
        await service.update_flow(flow_id=flow.id, steps=[step])
        published = await service.publish_flow(flow_id=flow.id)
        assert published.steps[0].output_mode == "copy_input"
    async with db_container() as container:
        session = container.session()
        assert (
            await session.scalar(
                sa.select(FlowSteps.output_mode).where(FlowSteps.flow_id == flow.id)
            )
            == "copy_input"
        )
        definition = await session.scalar(
            sa.select(FlowVersions.definition_json).where(
                FlowVersions.flow_id == flow.id
            )
        )
        assert definition["steps"][0]["output_mode"] == "copy_input"
        assert definition["steps"][0]["output_type"] == "json"
    async with db_container() as container:
        await container.flow_service().unpublish_flow(flow_id=flow.id)
    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    with pytest.raises(RuntimeError, match="1 flow step"):
        command.downgrade(config, "202610121300")
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    assert head is not None
    version = sa.text("SELECT version_num FROM alembic_version")
    async with db_container() as container:
        # Index revisions run outside a transaction, so those above the guard
        # can commit before it refuses; the guarded revision stays applied.
        # Develop's chains that do not descend from 202610121300 keep their
        # own version rows beside the flow chain's.
        stamps = set((await container.session().execute(version)).scalars())
        assert stamps & {
            revision.revision
            for revision in script.iterate_revisions(head, "202610121300")
        }
    # Those revisions are rerunnable, so an upgrade restores what they undid.
    command.upgrade(config, "head")
    async with db_container() as container:
        assert await container.session().scalar(version) == head
        await container.flow_service().update_flow(
            flow_id=flow.id,
            steps=[
                step.model_copy(
                    update={
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "compose_text",
                        "output_contract": None,
                    }
                )
            ],
        )
    try:
        command.downgrade(config, "202610121300")
    finally:
        # Later tests on this worker share the database: restore its schema.
        command.upgrade(config, "head")
    async with db_container() as container:
        await container.flow_service().update_flow(flow_id=flow.id, steps=[step])
        assert (await container.flow_service().publish_flow(flow_id=flow.id)).steps[
            0
        ].output_mode == "copy_input"
