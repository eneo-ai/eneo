"""Writes to integration knowledge against PostgreSQL: a rename made while a
sync holds the row keeps what the sync wrote."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.integration_table import (
    Integration,
    IntegrationKnowledge,
    TenantIntegration,
    UserIntegration,
)
from eneo.database.tables.spaces_table import Spaces, SpacesEmbeddingModels


@dataclass
class Setup:
    personal_space: UUID
    organization_space: UUID
    child_spaces: list[UUID]
    embedding_model: UUID
    connection: UUID


@pytest.fixture
async def setup(db_container, admin_user, embedding_model_factory) -> Setup:
    async with db_container() as container:
        session = container.session()
        model = await embedding_model_factory(session)
        personal = Spaces(
            name=f"personal-{uuid4().hex[:6]}",
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
        session.add(personal)
        await session.flush()
        organization = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        session.add(
            Spaces(
                name=f"child-{uuid4().hex[:6]}",
                tenant_id=admin_user.tenant_id,
                tenant_space_id=organization,
            )
        )
        await session.flush()
        children = (
            await session.scalars(
                sa.select(Spaces.id).where(Spaces.tenant_space_id == organization)
            )
        ).all()
        spaces = {"personal": personal.id, "organization": organization}
        await session.execute(
            sa.insert(SpacesEmbeddingModels),
            [
                dict(space_id=space_id, embedding_model_id=model.id)
                for space_id in spaces.values()
            ],
        )
        integration = Integration(
            name=f"sharepoint-{uuid4().hex[:8]}",
            description="SharePoint",
            integration_type="sharepoint",
        )
        session.add(integration)
        await session.flush()
        tenant_integration = TenantIntegration(
            tenant_id=admin_user.tenant_id, integration_id=integration.id
        )
        session.add(tenant_integration)
        await session.flush()
        connection = UserIntegration(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        session.add(connection)
        await session.flush()
        # Read before the commit expires the instances.
        built = Setup(
            personal_space=spaces["personal"],
            organization_space=spaces["organization"],
            child_spaces=sorted(children),
            embedding_model=model.id,
            connection=connection.id,
        )
    return built


async def test_a_rename_during_a_sync_keeps_what_the_sync_wrote(db_container, setup):
    async with db_container() as container:
        knowledge = IntegrationKnowledge(
            name="Protokoll",
            original_name="Protokoll",
            url="https://contoso.sharepoint.com/sites/KS/Protokoll",
            space_id=setup.personal_space,
            tenant_id=container.user().tenant_id,
            embedding_model_id=setup.embedding_model,
            user_integration_id=setup.connection,
            size=0,
            last_sync_status="never",
        )
        container.session().add(knowledge)
        await container.session().flush()
        knowledge_id = knowledge.id

    async with db_container() as sync:
        # The sync's first write locks the row until the sync commits.
        await sync.integration_knowledge_repo().update_sync_state(
            knowledge_id,
            delta_token="delta-after-first-import",
            size=52_000,
            last_sync_status="success",
            last_sync_summary={"files_processed": 12},
        )
        async with db_container() as rename:
            pid = await rename.session().scalar(sa.text("SELECT pg_backend_pid()"))
            pending = asyncio.create_task(
                rename.integration_knowledge_service().update_knowledge_name(
                    setup.personal_space, knowledge_id, "Protokoll KS"
                )
            )
            try:
                async with asyncio.timeout(10):
                    while not await sync.session().scalar(
                        sa.text(
                            "SELECT wait_event_type = 'Lock' "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": pid},
                    ):
                        if pending.done():
                            await pending
                            pytest.fail("The rename did not wait for the sync")
                        await asyncio.sleep(0.01)
                await sync.session().commit()
                renamed = await asyncio.wait_for(pending, timeout=10)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)

    # The response is read after the rename's write, so it shows the sync too.
    assert (renamed.name, renamed.delta_token, renamed.size) == (
        "Protokoll KS",
        "delta-after-first-import",
        52_000,
    )
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(
                    IntegrationKnowledge.name,
                    IntegrationKnowledge.original_name,
                    IntegrationKnowledge.delta_token,
                    IntegrationKnowledge.size,
                    IntegrationKnowledge.last_sync_status,
                    IntegrationKnowledge.last_sync_summary,
                ).where(IntegrationKnowledge.id == knowledge_id)
            )
        ).one()
    assert tuple(row) == (
        "Protokoll KS",
        "Protokoll",
        "delta-after-first-import",
        52_000,
        "success",
        {"files_processed": 12},
    )
