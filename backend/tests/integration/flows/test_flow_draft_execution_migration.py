from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.flow_tables import FlowRuns, Flows, FlowVersions


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.migration_isolation
async def test_draft_execution_migration_backfills_history_and_reverses(
    db_container, admin_user, completion_model_factory, space_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "draft-migration-model")
        space = await space_factory(session, "Draft migration", [model.id])
        flow = Flows(
            name="Published", tenant_id=admin_user.tenant_id, space_id=space.id
        )
        empty_flow = Flows(
            name="Empty", tenant_id=admin_user.tenant_id, space_id=space.id
        )
        session.add_all([flow, empty_flow])
        await session.flush()
        versions = [
            FlowVersions(
                flow_id=flow.id,
                version=number,
                tenant_id=admin_user.tenant_id,
                definition_json={"steps": [], "historical": number},
                definition_checksum=f"historical-checksum-{number}",
            )
            for number in (1, 3)
        ]
        session.add_all(versions)
        await session.flush()
        flow.published_version = 3
        run = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            tenant_id=admin_user.tenant_id,
            principal_type="user",
            principal_user_id=admin_user.id,
            trace_id=uuid4(),
            status="queued",
        )
        session.add(run)
        await session.flush()
        preserved = [
            (
                v.version,
                v.definition_json,
                v.definition_checksum,
                v.created_at,
                v.updated_at,
            )
            for v in versions
        ]
        path = (
            Path(__file__).parents[3]
            / "alembic/versions/202609161030_add_draft_execution_persistence.py"
        )
        spec = importlib.util.spec_from_file_location("draft_execution_migration", path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        # Chains from the capacity-window revision that landed just before it,
        # so the branch keeps a single head.
        assert migration.down_revision == "202609161000"

        def cycle(connection):
            assert sa.inspect(connection).has_table("flow_version_file_references")
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
                inspector = sa.inspect(connection)
                assert not inspector.has_table("flow_version_file_references")
                for table, fields in (
                    ("flows", {"snapshot_allocation_high_water_mark"}),
                    ("flow_versions", {"first_published_at", "source_draft_revision"}),
                    ("flow_runs", {"purpose"}),
                ):
                    assert not fields.intersection(
                        c["name"] for c in inspector.get_columns(table)
                    )
                assert "ck_flow_runs_purpose" not in {
                    c["name"] for c in inspector.get_check_constraints("flow_runs")
                }
                migration.upgrade()

        await (await session.connection()).run_sync(cycle)
        rows = (
            (
                await session.execute(
                    sa.select(FlowVersions)
                    .where(FlowVersions.flow_id == flow.id)
                    .order_by(FlowVersions.version)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        assert [
            (
                v.version,
                v.definition_json,
                v.definition_checksum,
                v.created_at,
                v.updated_at,
            )
            for v in rows
        ] == preserved
        assert all(v.first_published_at == v.created_at for v in rows)
        assert all(v.source_draft_revision is None for v in rows)
        marks = dict(
            (
                await session.execute(
                    sa.select(
                        Flows.id, Flows.snapshot_allocation_high_water_mark
                    ).where(Flows.id.in_([flow.id, empty_flow.id]))
                )
            ).all()
        )
        assert marks == {flow.id: 3, empty_flow.id: 0}
        assert (
            await session.scalar(
                sa.select(FlowRuns.purpose).where(FlowRuns.id == run.id)
            )
            == "production"
        )
