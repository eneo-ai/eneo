import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.ai_models_table import CompletionModels


def test_capacity_columns_are_nullable():
    assert CompletionModels.__table__.c.max_input_tokens.nullable
    assert CompletionModels.__table__.c.max_output_tokens.nullable


@pytest.mark.parametrize("missing", [None, "max_input_tokens", "max_output_tokens"])
def test_nullable_migration_preserves_data_and_guards_downgrade(missing):
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202609161100_nullable_model_capacity.py"
    )
    spec = importlib.util.spec_from_file_location("nullable_capacity", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "202609161030"
    with sa.create_engine("sqlite://").begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE completion_models (id INTEGER PRIMARY KEY, max_input_tokens INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO completion_models VALUES (1, 100, 80)")
        with patch.object(
            migration, "op", Operations(MigrationContext.configure(connection))
        ):
            migration.upgrade()
            assert connection.exec_driver_sql(
                "SELECT * FROM completion_models"
            ).one() == (1, 100, 80)
            assert all(
                column["nullable"]
                for column in sa.inspect(connection).get_columns("completion_models")
                if column["name"] != "id"
            )
            if missing:
                connection.execute(
                    sa.text(f"UPDATE completion_models SET {missing} = NULL")
                )
                with pytest.raises(RuntimeError, match="undeclared.*capacity"):
                    migration.downgrade()
                assert (
                    connection.execute(
                        sa.text(f"SELECT {missing} FROM completion_models")
                    ).scalar()
                    is None
                )
            else:
                migration.downgrade()
                assert connection.exec_driver_sql(
                    "SELECT * FROM completion_models"
                ).one() == (1, 100, 80)
                assert not any(
                    column["nullable"]
                    for column in sa.inspect(connection).get_columns(
                        "completion_models"
                    )
                    if column["name"] != "id"
                )
