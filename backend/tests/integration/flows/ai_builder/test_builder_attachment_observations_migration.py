"""Integration tests for the builder_attachment_observations table migration.

Verifies that the up → down → up cycle is drift-free for the new
tenant-scoped attachment-observation cache table:

- upgrade creates the table with the nine expected columns
- upgrade installs the composite primary key on five columns
- upgrade installs the tenant-scoped LRU index
- upgrade installs the tenants FK with CASCADE
- upgrade installs the per-field CHECK constraints
- downgrade drops the table
- a second upgrade restores everything identically

Run with:
    pytest -m migration_isolation \
        tests/integration/flows/ai_builder/test_builder_attachment_observations_migration.py -v
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_MIGRATION_REVISION = "20260424_builder_attachment_obs"
_PRIOR_REVISION = "20260423_builder_planning_state"

_TABLE_NAME = "builder_attachment_observations"

_EXPECTED_COLUMNS = {
    "tenant_id",
    "content_sha256",
    "digest_version",
    "fcm_version",
    "pattern_registry_version",
    "observation_json",
    "deterministic_signals_json",
    "created_at",
    "last_accessed_at",
}

_EXPECTED_PK_COLUMNS = [
    "tenant_id",
    "content_sha256",
    "digest_version",
    "fcm_version",
    "pattern_registry_version",
]

_LRU_INDEX_NAME = "ix_builder_attachment_obs_tenant_last_accessed"


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _table_exists(cur: psycopg2.extensions.cursor) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = %s
        """,
        (_TABLE_NAME,),
    )
    return cur.fetchone() is not None


def _present_columns(cur: psycopg2.extensions.cursor) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (_TABLE_NAME,),
    )
    return {row[0] for row in cur.fetchall()}


def _pk_columns(cur: psycopg2.extensions.cursor) -> list[str]:
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_name = kcu.table_name
        WHERE tc.table_name = %s
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position
        """,
        (_TABLE_NAME,),
    )
    return [row[0] for row in cur.fetchall()]


def _index_exists(cur: psycopg2.extensions.cursor, name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_indexes
        WHERE tablename = %s AND indexname = %s
        """,
        (_TABLE_NAME, name),
    )
    return cur.fetchone() is not None


def _tenants_fk_is_cascade(cur: psycopg2.extensions.cursor) -> bool:
    cur.execute(
        """
        SELECT rc.delete_rule
        FROM information_schema.table_constraints tc
        JOIN information_schema.referential_constraints rc
          ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.constraint_column_usage ccu
          ON rc.unique_constraint_name = ccu.constraint_name
        WHERE tc.table_name = %s
          AND tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_name = 'tenants'
        """,
        (_TABLE_NAME,),
    )
    row = cur.fetchone()
    return row is not None and row[0] == "CASCADE"


def _check_constraint_names(cur: psycopg2.extensions.cursor) -> set[str]:
    cur.execute(
        """
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.table_name = %s
          AND tc.constraint_type = 'CHECK'
        """,
        (_TABLE_NAME,),
    )
    return {row[0] for row in cur.fetchall()}


def _current_revision(cur: psycopg2.extensions.cursor) -> str | None:
    cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
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
    """Run the full up → down → up cycle and expose per-phase snapshots."""
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
        command.upgrade(cfg, "head")
        command.downgrade(cfg, _PRIOR_REVISION)

        with conn.cursor() as cur:
            assert _current_revision(cur) == _PRIOR_REVISION, (
                f"Expected DB at {_PRIOR_REVISION!r} before test upgrade"
            )
            assert not _table_exists(cur), (
                "Table must not exist before the upgrade under test"
            )

        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            first_up_exists = _table_exists(cur)
            first_up_cols = _present_columns(cur)
            first_up_pk = _pk_columns(cur)
            first_up_lru = _index_exists(cur, _LRU_INDEX_NAME)
            first_up_fk_cascade = _tenants_fk_is_cascade(cur)
            first_up_checks = _check_constraint_names(cur)

        command.downgrade(cfg, "-1")
        with conn.cursor() as cur:
            down_exists = _table_exists(cur)

        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            second_up_exists = _table_exists(cur)
            second_up_cols = _present_columns(cur)
            second_up_pk = _pk_columns(cur)
            second_up_lru = _index_exists(cur, _LRU_INDEX_NAME)

        command.upgrade(cfg, "head")

        yield {
            "after_first_upgrade": {
                "exists": first_up_exists,
                "columns": first_up_cols,
                "pk_columns": first_up_pk,
                "lru_index": first_up_lru,
                "fk_cascade": first_up_fk_cascade,
                "check_constraints": first_up_checks,
            },
            "after_downgrade": {"exists": down_exists},
            "after_second_upgrade": {
                "exists": second_up_exists,
                "columns": second_up_cols,
                "pk_columns": second_up_pk,
                "lru_index": second_up_lru,
            },
        }
    finally:
        conn.close()


class TestAttachmentObservationsMigration:
    def test_upgrade_creates_table(self, migration_round_trip):
        assert migration_round_trip["after_first_upgrade"]["exists"], (
            f"Table {_TABLE_NAME!r} must exist after upgrade"
        )

    def test_upgrade_has_expected_columns(self, migration_round_trip):
        assert (
            migration_round_trip["after_first_upgrade"]["columns"] == _EXPECTED_COLUMNS
        )

    def test_upgrade_primary_key_is_composite(self, migration_round_trip):
        assert (
            migration_round_trip["after_first_upgrade"]["pk_columns"]
            == _EXPECTED_PK_COLUMNS
        )

    def test_upgrade_creates_lru_index(self, migration_round_trip):
        assert migration_round_trip["after_first_upgrade"]["lru_index"], (
            f"Index {_LRU_INDEX_NAME!r} must exist after upgrade"
        )

    def test_upgrade_tenants_fk_is_cascade(self, migration_round_trip):
        assert migration_round_trip["after_first_upgrade"]["fk_cascade"], (
            "FK to tenants.id must be ON DELETE CASCADE"
        )

    def test_upgrade_installs_all_expected_check_constraints(
        self, migration_round_trip
    ):
        checks = migration_round_trip["after_first_upgrade"]["check_constraints"]
        expected = {
            "ck_builder_attachment_obs_sha256_length",
            "ck_builder_attachment_obs_digest_version",
            "ck_builder_attachment_obs_fcm_version",
            "ck_builder_attachment_obs_pattern_registry_version",
        }
        assert expected.issubset(checks), (
            f"Missing check constraints: {expected - checks}"
        )

    def test_downgrade_drops_table(self, migration_round_trip):
        assert not migration_round_trip["after_downgrade"]["exists"], (
            f"Table {_TABLE_NAME!r} must be absent after downgrade"
        )

    def test_second_upgrade_restores_table(self, migration_round_trip):
        state = migration_round_trip["after_second_upgrade"]
        assert state["exists"]
        assert state["columns"] == _EXPECTED_COLUMNS
        assert state["pk_columns"] == _EXPECTED_PK_COLUMNS
        assert state["lru_index"]
