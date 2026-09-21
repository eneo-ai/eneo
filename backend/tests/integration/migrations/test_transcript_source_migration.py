from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.flow_tables import FlowStepTranscriptSources

pytestmark = pytest.mark.migration_isolation


@pytest.mark.parametrize("failed_index", [1, 2, 3])
def test_source_table_creation_rolls_back_and_can_be_retried(
    setup_database, test_settings, monkeypatch, failed_index
):
    migration = runpy.run_path(
        str(
            Path(__file__).parents[3]
            / "alembic/versions/202609211100_add_flow_step_transcript_sources.py"
        )
    )
    engine = sa.create_engine(test_settings.sync_database_url)
    upgrade = migration["upgrade"]
    downgrade = migration["downgrade"]
    table = FlowStepTranscriptSources.__table__
    try:
        with engine.begin() as connection:
            monkeypatch.setitem(
                downgrade.__globals__,
                "op",
                Operations(MigrationContext.configure(connection)),
            )
            downgrade()
        with pytest.raises(RuntimeError, match="index creation interrupted"):
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                create_index = operations.create_index
                count = 0

                def interrupted_index(*args, **kwargs):
                    nonlocal count
                    create_index(*args, **kwargs)
                    count += 1
                    if count == failed_index:
                        raise RuntimeError("index creation interrupted")

                monkeypatch.setattr(operations, "create_index", interrupted_index)
                monkeypatch.setitem(upgrade.__globals__, "op", operations)
                upgrade()
        with engine.connect() as fresh:
            assert not sa.inspect(fresh).has_table(table.name)
    finally:
        with engine.begin() as connection:
            if not sa.inspect(connection).has_table(table.name):
                monkeypatch.setitem(
                    upgrade.__globals__,
                    "op",
                    Operations(MigrationContext.configure(connection)),
                )
                upgrade()
        engine.dispose()
    with engine.connect() as fresh:
        inspector = sa.inspect(fresh)
        assert {column["name"] for column in inspector.get_columns(table.name)} == set(
            table.columns.keys()
        )
        assert {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table.name)
        } == {("flow_run_id", "step_id", "attempt_no")}
        assert all(
            fk["options"]["ondelete"] == "CASCADE"
            for fk in inspector.get_foreign_keys(table.name)
        )
    engine.dispose()
