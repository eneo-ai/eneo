import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_removes_only_retired_policy_and_is_repeatable(
    setup_database, monkeypatch
):
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202610081100_retire_flow_upload_size_overrides.py"
    )
    spec = importlib.util.spec_from_file_location("retire_flow_sizes", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    values = [
        {
            "input_limits": {
                "file_max_size_bytes": 10,
                "audio_max_size_bytes": 20,
                "max_files_per_run": 7,
            },
            "other": {"keep": True},
        },
        None,
        {"input_limits": "file_max_size_bytes"},
        {"input_limits": ["audio_max_size_bytes"]},
        {"input_limits": {"audio_max_duration_seconds": 600}},
    ]
    expected = [
        {"input_limits": {"max_files_per_run": 7}, "other": {"keep": True}},
        *values[1:],
    ]
    async with sessionmanager.session() as session, session.begin():
        # A transaction-local table shadows tenants while exercising the exact migration SQL.
        await session.execute(
            sa.text(
                "CREATE TEMP TABLE tenants (id uuid PRIMARY KEY, flow_settings jsonb) ON COMMIT DROP"
            )
        )
        table = sa.table(
            "tenants",
            sa.column("id", sa.UUID),
            sa.column("flow_settings", sa.dialects.postgresql.JSONB),
        )
        ids = [uuid4() for _ in values]
        await session.execute(
            table.insert(),
            [{"id": id_, "flow_settings": value} for id_, value in zip(ids, values)],
        )
        connection = await session.connection()

        def run_migration(sync_connection):
            monkeypatch.setattr(migration.op, "get_bind", lambda: sync_connection)
            migration.upgrade()
            migration.upgrade()
            migration.downgrade()

        await connection.run_sync(run_migration)
        rows = dict(
            (await session.execute(sa.select(table.c.id, table.c.flow_settings))).all()
        )
        assert [rows[id_] for id_ in ids] == expected
