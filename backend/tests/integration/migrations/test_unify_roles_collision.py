"""Integration test for the unify_roles migration collision preflight.

Verifies that `20260324_unify_roles_system` halts cleanly when a tenant has a
custom role whose name collides with a template ("Owner" / "User" /
"AI Configurator"). The preflight must:

  * raise a RuntimeError naming each colliding role
  * leave the database at the pre-migration revision (transactional DDL)
  * succeed when re-run after the collision is resolved

Run in isolation alongside the existing migration tests:
    pytest -m migration_isolation tests/integration/migrations/test_unify_roles_collision.py -v
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


# Revision that unify_roles depends on, where predefined_roles and
# users_predefined_roles still exist and unify_roles has not yet run.
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


@pytest.fixture
def pre_unify_db(test_settings):
    """Bring the DB to the revision just before unify_roles and yield a
    psycopg2 connection plus a seed helper.

    Each test controls which collisions to introduce via the seed helper.
    Teardown closes the connection without restoring schema — each invocation
    re-normalizes at setup, and migration_isolation tests are run separately
    from the default suite so lingering state doesn't affect other tests.
    """
    cfg = _alembic_cfg(test_settings.sync_database_url)

    # The DB may be at head (typical), at base (fresh container), or somewhere
    # in between (previous test left it partway). Downgrade only works from a
    # descendant of PRE_UNIFY_REVISION, so fall back to upgrade when it isn't.
    try:
        command.downgrade(cfg, PRE_UNIFY_REVISION)
    except Exception:
        command.upgrade(cfg, PRE_UNIFY_REVISION)

    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    # The default setup_database seeds the test tenant with its own "Owner"
    # role. That's a pre-existing collision against the template before any
    # test runs, so clear any existing same-named roles first — each test
    # controls which collisions (if any) to introduce.
    _clear_template_named_roles(conn)

    # The preflight joins `roles` against `predefined_roles`. On develop that
    # table was populated at runtime by a startup seeder; the migration tests
    # don't run the app, so seed the three templates so the JOIN has rows
    # to match against.
    _ensure_predefined_roles_seeded(conn)

    def _seed(role_name: str) -> tuple[str, str]:
        return _insert_tenant_and_colliding_role(conn, role_name=role_name)

    try:
        yield {"conn": conn, "cfg": cfg, "seed": _seed}
    finally:
        conn.close()
        # Migration_isolation tests don't restore the shared fixture state;
        # leave the DB at whatever revision the test ended on, and let the
        # next fixture invocation downgrade/upgrade into the required shape.


_PREDEFINED_TEMPLATES = (
    ("Owner", ["admin", "assistants", "services", "collections"]),
    ("User", ["assistants", "collections"]),
    ("AI Configurator", ["assistants", "services", "AI"]),
)
_TEMPLATE_NAMES = [name for name, _ in _PREDEFINED_TEMPLATES]


def _clear_template_named_roles(conn) -> None:
    """Remove any pre-existing roles whose names collide with templates.

    The default test-DB seed adds an "Owner" role for the test tenant; wiping
    those first lets each test introduce exactly the collisions it wants to
    assert on, and keeps the final upgrade-to-head path clean for re-runs.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM users_roles WHERE role_id IN ("
            "SELECT id FROM roles WHERE name = ANY(%s))",
            (_TEMPLATE_NAMES,),
        )
        cur.execute(
            "DELETE FROM roles WHERE name = ANY(%s)",
            (_TEMPLATE_NAMES,),
        )


def _ensure_predefined_roles_seeded(conn) -> None:
    """Seed the three template rows into `predefined_roles` if absent.

    The exact permission sets don't matter — the preflight only joins on name.
    """
    with conn.cursor() as cur:
        for name, perms in _PREDEFINED_TEMPLATES:
            cur.execute(
                """
                INSERT INTO predefined_roles (name, permissions)
                VALUES (%s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, perms),
            )


def _insert_tenant_and_colliding_role(conn, *, role_name: str) -> tuple[str, str]:
    """Insert a tenant and a custom role with a template-clashing name.

    Returns (tenant_id, role_id).
    """
    now = datetime.now(timezone.utc)
    tenant_id = str(uuid4())
    role_id = str(uuid4())

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, state, quota_limit, created_at, updated_at)
            VALUES (%s, %s, 'active', 1000000, %s, %s)
            """,
            (tenant_id, f"collision-tenant-{uuid4().hex[:6]}", now, now),
        )
        cur.execute(
            """
            INSERT INTO roles
                (id, name, permissions, tenant_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (role_id, role_name, ["assistants"], tenant_id, now, now),
        )

    return tenant_id, role_id


class TestUnifyRolesCollisionPreflight:
    """Preflight halts on name collisions and is rerun-safe after resolution."""

    def test_upgrade_halts_when_custom_role_collides_with_template(self, pre_unify_db):
        cfg = pre_unify_db["cfg"]

        tenant_id, role_id = pre_unify_db["seed"]("Owner")

        with pytest.raises(RuntimeError) as exc_info:
            command.upgrade(cfg, UNIFY_REVISION)

        message = str(exc_info.value)
        assert "unify_roles migration halted" in message
        assert tenant_id in message
        assert role_id in message
        assert "Owner" in message

    def test_database_stays_at_previous_revision_when_preflight_fails(
        self, pre_unify_db
    ):
        conn = pre_unify_db["conn"]
        cfg = pre_unify_db["cfg"]

        pre_unify_db["seed"]("User")

        with pytest.raises(RuntimeError):
            command.upgrade(cfg, UNIFY_REVISION)

        # The predefined_source column is only added *after* the preflight,
        # so its absence proves the upgrade was rolled back atomically.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'roles' AND column_name = 'predefined_source'
                """
            )
            assert cur.fetchone() is None

            # predefined_roles must still exist since drop only runs after preflight.
            cur.execute(
                """
                SELECT to_regclass('predefined_roles')
                """
            )
            assert cur.fetchone()[0] is not None

    def test_upgrade_succeeds_after_colliding_role_is_renamed(self, pre_unify_db):
        conn = pre_unify_db["conn"]
        cfg = pre_unify_db["cfg"]

        tenant_id, role_id = pre_unify_db["seed"]("AI Configurator")

        with pytest.raises(RuntimeError):
            command.upgrade(cfg, UNIFY_REVISION)

        # Simulate the operator renaming the custom role as instructed
        # by the preflight message, then re-running the migration.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE roles SET name = %s WHERE id = %s",
                ("AI Configurator (legacy)", role_id),
            )

        command.upgrade(cfg, UNIFY_REVISION)

        # The templates should now be seeded for the tenant alongside the
        # preserved renamed custom role.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, predefined_source
                FROM roles
                WHERE tenant_id = %s
                ORDER BY name
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

        names = {name for name, _ in rows}
        assert "AI Configurator" in names  # seeded template
        assert "AI Configurator (legacy)" in names  # preserved custom role
        assert "Owner" in names
        assert "User" in names

        # Renamed custom role remains untagged
        legacy_source = next(
            src for name, src in rows if name == "AI Configurator (legacy)"
        )
        assert legacy_source is None

        # Seeded templates are tagged
        seeded_source = next(src for name, src in rows if name == "AI Configurator")
        assert seeded_source == "AI Configurator"
