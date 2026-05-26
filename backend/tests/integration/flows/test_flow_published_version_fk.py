from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.tables.flow_tables import Flows, FlowVersions


@pytest.mark.asyncio
@pytest.mark.integration
async def test_published_version_fk_enforces_existing_flow_version(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "published-fk-model")
        space = await space_factory(session, "Published FK space", [model.id])
        flow_id = uuid4()

        await session.execute(
            sa.insert(Flows).values(
                id=flow_id,
                name="Published pointer invariant",
                description=None,
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                created_by_user_id=admin_user.id,
                owner_user_id=admin_user.id,
                published_version=None,
                metadata_json=None,
                data_retention_days=None,
                draft_revision=0,
                deleted_at=None,
            )
        )
        await session.execute(
            sa.insert(FlowVersions).values(
                flow_id=flow_id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_checksum="published-pointer-invariant-v1",
                definition_json={"steps": []},
            )
        )
        await session.flush()

        await session.execute(
            sa.update(Flows).where(Flows.id == flow_id).values(published_version=1)
        )
        await session.flush()
        published_version = await session.scalar(
            sa.select(Flows.published_version).where(Flows.id == flow_id)
        )
        assert published_version == 1

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    sa.update(Flows)
                    .where(Flows.id == flow_id)
                    .values(published_version=2)
                )
                await session.flush()

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    sa.delete(FlowVersions)
                    .where(FlowVersions.flow_id == flow_id)
                    .where(FlowVersions.version == 1)
                )
                await session.flush()

        await session.execute(
            sa.update(Flows).where(Flows.id == flow_id).values(published_version=None)
        )
        await session.execute(
            sa.delete(FlowVersions)
            .where(FlowVersions.flow_id == flow_id)
            .where(FlowVersions.version == 1)
        )
        await session.flush()

        remaining_version_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowVersions)
            .where(FlowVersions.flow_id == flow_id)
        )
        assert remaining_version_count == 0
