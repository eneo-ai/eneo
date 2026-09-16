import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_context_window_migration_preserves_rows_and_is_reversible() -> None:
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202609161000_add_context_window_tokens.py"
    )
    spec = importlib.util.spec_from_file_location("context_window_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE completion_models (id INTEGER PRIMARY KEY, max_input_tokens INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO completion_models VALUES (1, 100, 80)")
        with patch.object(
            migration, "op", Operations(MigrationContext.configure(connection))
        ):
            migration.upgrade()
            columns = {
                column["name"]: column
                for column in sa.inspect(connection).get_columns("completion_models")
            }
            assert columns["context_window_tokens"]["nullable"] is True
            assert connection.exec_driver_sql(
                "SELECT * FROM completion_models"
            ).one() == (1, 100, 80, None)
            migration.downgrade()
            assert connection.exec_driver_sql(
                "SELECT * FROM completion_models"
            ).one() == (1, 100, 80)
            assert "context_window_tokens" not in {
                column["name"]
                for column in sa.inspect(connection).get_columns("completion_models")
            }
