"""Complete keysets must serve pages even when many roots share a timestamp."""

import io
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.flow_tables import BuilderClientErrors
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions


@pytest.mark.parametrize(
    "model,name,columns",
    [
        (
            Questions,
            "ix_questions_retention_owner_created_id",
            ("assistant_id", "created_at", "id"),
        ),
        (
            AppRuns,
            "ix_app_runs_retention_owner_created_id",
            ("app_id", "created_at", "id"),
        ),
        (Sessions, "ix_sessions_created_id", ("created_at", "id")),
        (
            BuilderClientErrors,
            "ix_builder_client_errors_created_id",
            ("created_at", "id"),
        ),
    ],
)
def test_metadata_indexes_the_entire_conversation_keyset(model, name, columns):
    """Kills omission of the id tie-breaker, which sorts every timestamp tie."""
    indexes = [index for index in model.__table__.indexes if index.name == name]
    assert len(indexes) == 1
    assert tuple(column.name for column in indexes[0].columns) == columns


@pytest.mark.parametrize(
    "before,after,shapes,direction,new_count,old_count",
    [
        (before, after, shapes, direction, new_count, old_count)
        for before, after, shapes in [
            (
                "202610051020",
                "202610061200",
                (
                    "questions (assistant_id, created_at, id)",
                    "app_runs (app_id, created_at, id)",
                ),
            ),
            (
                "202610061200",
                "202610061600",
                ("sessions (created_at, id)", "builder_client_errors (created_at, id)"),
            ),
        ]
        for direction, new_count, old_count in [("upgrade", 2, 3), ("downgrade", 3, 2)]
    ],
)
def test_offline_migration_replaces_indexes_concurrently(
    before, after, shapes, direction, new_count, old_count
):
    """Kills online-only inspection, missing downgrade, or blocking index builds."""
    output = io.StringIO()
    config = Config(
        str(Path(__file__).parents[2] / "alembic.ini"), output_buffer=output
    )
    config.set_main_option(
        "sqlalchemy.url", "postgresql://offline:offline@localhost/offline"
    )
    if direction == "upgrade":
        command.upgrade(config, f"{before}:{after}", sql=True)
    else:
        command.downgrade(config, f"{after}:{before}", sql=True)
    sql = output.getvalue()
    assert sql.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == new_count
    assert sql.count("DROP INDEX CONCURRENTLY IF EXISTS") == old_count
    assert "pg_index" not in sql
    assert sql.rindex("RESET lock_timeout") > sql.rindex("DROP INDEX")
    if direction == "upgrade":
        assert sql.rindex("CREATE INDEX") < sql.index("DROP INDEX")
        for shape in shapes:
            assert f"ON {shape}" in sql
