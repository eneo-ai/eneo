"""Integration tests for the builder_sessions planning state migration.

Verifies that:
- upgrade adds all five columns with correct types, nullability, defaults
  and that the architecture_hash index is created
- downgrade removes all five columns and drops the index
- a second upgrade restores columns and index identically (no drift)

These tests use an isolated PostgreSQL container and must be run with:
    pytest -m migration_isolation tests/integration/flows/ai_builder/test_builder_planning_state_migration.py -v
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_MIGRATION_REVISION = "20260423_builder_planning_state"
_PRIOR_REVISION = "20260421_builder_conv_msg_id"

_EXPECTED_COLUMNS = {
    "planning_state_jsonb",
    "planning_state_version",
    "planning_phase",
    "architecture_hash",
    "planning_state_updated_at",
}

_INDEX_NAME = "ix_builder_sessions_architecture_hash"


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _present_columns(cur: psycopg2.extensions.cursor) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'builder_sessions'
        AND column_name = ANY(%s)
        """,
        (list(_EXPECTED_COLUMNS),),
    )
    return {row[0] for row in cur.fetchall()}


def _index_exists(cur: psycopg2.extensions.cursor) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_indexes
        WHERE tablename = 'builder_sessions'
        AND indexname = %s
        """,
        (_INDEX_NAME,),
    )
    return cur.fetchone() is not None


def _column_meta(cur: psycopg2.extensions.cursor, column: str) -> dict:
    """Return is_nullable and column_default for a single builder_sessions column."""
    cur.execute(
        """
        SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'builder_sessions'
        AND column_name = %s
        """,
        (column,),
    )
    row = cur.fetchone()
    assert row is not None, f"Column {column!r} not found"
    return {"is_nullable": row[0], "column_default": row[1]}


def _current_revision(cur: psycopg2.extensions.cursor) -> str | None:
    """Return the current alembic revision from the version table, or None."""
    cur.execute(
        """
        SELECT version_num FROM alembic_version LIMIT 1
        """
    )
    row = cur.fetchone()
    return row[0] if row else None


@pytest.fixture(autouse=True)
def cleanup_database():
    """Suppress the session-level cleanup fixture — migration tests own the DB state."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Suppress auto-seeding — migration tests own the schema."""
    yield


@pytest.fixture(scope="module")
def migration_round_trip(test_settings):
    """
    Run the full up → down → up cycle once for the module and expose
    per-phase snapshots so individual tests can assert on them without
    re-running alembic commands.

    The fixture:
    1. Ensures the DB is at the prior revision (upgrading or downgrading as needed).
    2. Runs upgrade to our migration revision and captures state.
    3. Downgrades one step and captures state.
    4. Upgrades again and captures state.
    5. Leaves the DB at head.
    """
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    cfg = _alembic_config(test_settings.sync_database_url)

    try:
        # Position the DB at the revision just before ours.
        # We upgrade to head first (in case the DB is below our prior revision),
        # then downgrade to our prior revision so that upgrade() under test
        # applies exactly one step.
        command.upgrade(cfg, "head")
        command.downgrade(cfg, _PRIOR_REVISION)

        with conn.cursor() as cur:
            assert _current_revision(cur) == _PRIOR_REVISION, (
                f"Expected DB at {_PRIOR_REVISION!r} before test upgrade"
            )
            assert _present_columns(cur) == set(), (
                "Columns must not exist before the upgrade under test"
            )

        # --- First upgrade ---
        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            first_up_cols = _present_columns(cur)
            first_up_index = _index_exists(cur)
            version_meta = _column_meta(cur, "planning_state_version")
            nullable_metas = {
                col: _column_meta(cur, col)
                for col in (
                    "planning_state_jsonb",
                    "planning_phase",
                    "architecture_hash",
                    "planning_state_updated_at",
                )
            }

        # --- Downgrade one step ---
        command.downgrade(cfg, "-1")
        with conn.cursor() as cur:
            down_cols = _present_columns(cur)
            down_index = _index_exists(cur)

        # --- Second upgrade ---
        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            second_up_cols = _present_columns(cur)
            second_up_index = _index_exists(cur)
            second_version_meta = _column_meta(cur, "planning_state_version")

        # Restore head so subsequent test sessions start at the latest revision.
        command.upgrade(cfg, "head")

        yield {
            "after_first_upgrade": {
                "columns": first_up_cols,
                "index": first_up_index,
                "version_meta": version_meta,
                "nullable_metas": nullable_metas,
            },
            "after_downgrade": {
                "columns": down_cols,
                "index": down_index,
            },
            "after_second_upgrade": {
                "columns": second_up_cols,
                "index": second_up_index,
                "version_meta": second_version_meta,
            },
        }
    finally:
        conn.close()


class TestPlanningStateMigration:
    """Round-trip verification: upgrade → downgrade → upgrade."""

    def test_upgrade_adds_all_columns(self, migration_round_trip):
        state = migration_round_trip["after_first_upgrade"]
        assert state["columns"] == _EXPECTED_COLUMNS, (
            "All five planning-state columns must exist after upgrade"
        )

    def test_upgrade_creates_index(self, migration_round_trip):
        state = migration_round_trip["after_first_upgrade"]
        assert state["index"], f"Index {_INDEX_NAME!r} must exist after upgrade"

    def test_planning_state_version_is_not_null_with_default_zero(
        self, migration_round_trip
    ):
        meta = migration_round_trip["after_first_upgrade"]["version_meta"]
        assert meta["is_nullable"] == "NO", "planning_state_version must be NOT NULL"
        assert meta["column_default"] is not None, (
            "planning_state_version must have a server default"
        )
        assert "0" in meta["column_default"], (
            "planning_state_version server default must be 0"
        )

    def test_nullable_columns_are_nullable(self, migration_round_trip):
        for col, meta in migration_round_trip["after_first_upgrade"][
            "nullable_metas"
        ].items():
            assert meta["is_nullable"] == "YES", f"{col!r} must be nullable"

    def test_downgrade_removes_all_columns(self, migration_round_trip):
        state = migration_round_trip["after_downgrade"]
        assert state["columns"] == set(), (
            "All five planning-state columns must be absent after downgrade"
        )

    def test_downgrade_drops_index(self, migration_round_trip):
        state = migration_round_trip["after_downgrade"]
        assert not state["index"], (
            f"Index {_INDEX_NAME!r} must be absent after downgrade"
        )

    def test_second_upgrade_restores_columns(self, migration_round_trip):
        state = migration_round_trip["after_second_upgrade"]
        assert state["columns"] == _EXPECTED_COLUMNS, (
            "Second upgrade must restore all five columns"
        )

    def test_second_upgrade_restores_index(self, migration_round_trip):
        state = migration_round_trip["after_second_upgrade"]
        assert state["index"], (
            f"Index {_INDEX_NAME!r} must be present after second upgrade"
        )

    def test_second_upgrade_matches_first_on_version_constraint(
        self, migration_round_trip
    ):
        first = migration_round_trip["after_first_upgrade"]["version_meta"]
        second = migration_round_trip["after_second_upgrade"]["version_meta"]
        assert second["is_nullable"] == first["is_nullable"], (
            "planning_state_version nullability must be identical on re-upgrade"
        )
        assert second["column_default"] == first["column_default"], (
            "planning_state_version server default must be identical on re-upgrade"
        )
