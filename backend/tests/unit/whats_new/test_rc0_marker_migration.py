"""Run the actual data migration against SQL rows without an application server."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_corrects_only_rc0_markers_and_preserves_independent_progress():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/202610191000_correct_rc0_whats_new_markers.py"
    )
    spec = spec_from_file_location("rc0_marker_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE whats_new_state (user_id INTEGER PRIMARY KEY, "
            "seen_version TEXT, announced_version TEXT)"
        )
        rows = [
            (1, "2.3.0", "2.3.0"),
            (2, None, "2.3.0"),
            (3, "2.3.0", "2.2.0"),
            (4, "2.2.0", None),
            (5, "2.3.0-rc.1", "2.3.0-rc.2"),
            (6, None, None),
            (7, "2.4.0", "2.4.0"),
        ]
        connection.exec_driver_sql("INSERT INTO whats_new_state VALUES (?, ?, ?)", rows)
        expected = [
            (
                user_id,
                "2.3.0-rc.0" if seen == "2.3.0" else seen,
                "2.3.0-rc.0" if announced == "2.3.0" else announced,
            )
            for user_id, seen, announced in rows
        ]
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            migration.downgrade()
        assert (
            list(
                connection.exec_driver_sql(
                    "SELECT user_id, seen_version, announced_version FROM whats_new_state ORDER BY user_id"
                )
            )
            == expected
        )
    engine.dispose()
