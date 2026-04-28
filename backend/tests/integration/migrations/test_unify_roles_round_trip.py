"""Integration test for the unify_roles migration round-trip.

Verifies that `20260324_unify_roles_system` can upgrade → downgrade → upgrade
against a scratch database without structural drift. The critical invariant
is the `roles.permissions` NOT NULL flip:

  * After upgrade: `roles.permissions` is NOT NULL (step 8 tightens).
  * After downgrade: `roles.permissions` is nullable again (downgrade loosens
    so lingering NULL rows don't block the reverse operation).
  * Re-upgrade succeeds without error.

This guards against a class of bugs where a downgrade step quietly ends up as
dead code — e.g. two `def downgrade()` definitions in the same module (Python
binds the second, first is silently skipped). A round-trip is the cheapest
way to surface that regression.

The round-trip is also known-LOSSY per the migration's downgrade docstring:
customizations across tenants are collapsed by `DISTINCT ON` on re-upgrade.
That's accepted behavior — this test focuses on the schema shape flip, not
row-level fidelity.

Run in isolation alongside the existing migration tests:
    pytest -m migration_isolation tests/integration/migrations/test_unify_roles_round_trip.py -v
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


PRE_UNIFY_REVISION = "202604101000"
UNIFY_REVISION = "unify_roles"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override shared cleanup_database so schema revisions persist across
    downgrade/upgrade cycles within this module.
    """
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override shared seed_default_models — this module seeds its own data."""
    yield


_TEMPLATE_NAMES = ["Owner", "User", "AI Configurator"]


def _clear_template_named_roles(conn) -> None:
    """Remove roles whose names collide with templates.

    Required because sibling migration tests (e.g. test_unify_roles_collision)
    seed template-named custom roles and may leave the DB at PRE_UNIFY with
    collisions present. The unify_roles preflight would halt re-upgrade on
    those rows — clear them so this fixture can return the DB to a known
    post-upgrade state regardless of predecessor state.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('predefined_roles'), to_regclass('users_roles')"
        )
        predefined_exists, users_roles_exists = cur.fetchone()

        if users_roles_exists is not None:
            cur.execute(
                "DELETE FROM users_roles WHERE role_id IN ("
                "SELECT id FROM roles WHERE name = ANY(%s))",
                (_TEMPLATE_NAMES,),
            )
        cur.execute(
            "DELETE FROM roles WHERE name = ANY(%s)",
            (_TEMPLATE_NAMES,),
        )


@pytest.fixture
def round_trip_db(test_settings):
    """Yield a psycopg2 connection with the DB normalized to the unify_roles
    revision so tests can drive downgrade/upgrade cycles from a known state.

    Teardown leaves schema at whatever the test ended on — isolation from
    other suites is the `migration_isolation` marker's job.
    """
    cfg = _alembic_cfg(test_settings.sync_database_url)

    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    # Clear collisions that sibling migration tests may have left behind, so
    # the unify_roles preflight doesn't halt re-upgrade.
    _clear_template_named_roles(conn)

    # Normalize to unify_roles head. The DB may be at head, at base, or mid-
    # way; upgrade is idempotent-ish (Alembic no-ops when already at head).
    command.upgrade(cfg, UNIFY_REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _get_column_is_nullable(conn, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        row = cur.fetchone()
        assert row is not None, f"column {table}.{column} not found"
        return row[0] == "YES"


def _table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        return cur.fetchone()[0] is not None


def _get_current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        return row[0] if row else None


class TestUnifyRolesRoundTrip:
    """upgrade → downgrade → upgrade restores the expected schema shape."""

    def test_permissions_not_null_after_upgrade(self, round_trip_db):
        """Baseline: step 8 leaves roles.permissions NOT NULL."""
        conn = round_trip_db["conn"]

        assert _get_current_revision(conn) == UNIFY_REVISION
        assert _get_column_is_nullable(conn, "roles", "permissions") is False

    def test_downgrade_loosens_permissions_to_nullable(self, round_trip_db):
        """Downgrade step 1 flips roles.permissions back to nullable.

        This is the regression guard for the duplicate `def downgrade()` bug:
        if Python bound a second, dead definition, this loosener would be
        silently skipped and the column would remain NOT NULL after downgrade.
        """
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_UNIFY_REVISION)

        assert _get_current_revision(conn) == PRE_UNIFY_REVISION
        assert _get_column_is_nullable(conn, "roles", "permissions") is True

    def test_downgrade_recreates_predefined_tables(self, round_trip_db):
        """Downgrade recreates predefined_roles + users_predefined_roles."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_UNIFY_REVISION)

        assert _table_exists(conn, "predefined_roles")
        assert _table_exists(conn, "users_predefined_roles")

    def test_downgrade_drops_post_unify_columns(self, round_trip_db):
        """Downgrade removes predefined_source and tenants.default_role_id."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_UNIFY_REVISION)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'roles' AND column_name = 'predefined_source'
                """
            )
            assert cur.fetchone() is None

            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'tenants' AND column_name = 'default_role_id'
                """
            )
            assert cur.fetchone() is None

    def test_upgrade_after_downgrade_restores_not_null(self, round_trip_db):
        """Full round-trip: upgrade → downgrade → upgrade → NOT NULL again.

        Proves the upgrade path is re-runnable against a freshly-downgraded
        schema without operator intervention — the practical signal that a
        rollback is recoverable.
        """
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_UNIFY_REVISION)
        assert _get_column_is_nullable(conn, "roles", "permissions") is True

        command.upgrade(cfg, UNIFY_REVISION)

        assert _get_current_revision(conn) == UNIFY_REVISION
        assert _get_column_is_nullable(conn, "roles", "permissions") is False
        assert not _table_exists(conn, "predefined_roles")
        assert not _table_exists(conn, "users_predefined_roles")
