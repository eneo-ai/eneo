"""Revision 202609251200: oversight visits members keep seeing. A new, empty
table whose rows follow their space and outlive their user; a downgrade
restores the oversight head exactly and leaves every other row alone."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest
from psycopg2 import errors
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import (
    test_admin_space_oversight_migration as oversight,
)
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand
from tests.integration.migrations import test_widget_migrations as widget_migrations

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PARENT = oversight.OVERSIGHT
VISITS = "202609251200"
TABLE = "space_oversight_visits"
REASON = oversight.REASON


@pytest.fixture(scope="module")
def postgres() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="visits_migration",
        password="visits_migration_password",
        dbname="visits_migration",
    ) as container:
        command.upgrade(expand._alembic_config(container.get_connection_url()), PARENT)
        yield container


@pytest.fixture
def database(postgres: PostgresContainer) -> Generator[str, None, None]:
    database_url = postgres.get_connection_url()
    try:
        yield database_url
    finally:
        command.downgrade(expand._alembic_config(database_url), PARENT)


def _visit(database_url: str, **values: object) -> str:
    visit_id = str(uuid4())
    row = {"id": visit_id, "role": "viewer", "reason": REASON, **values}
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    oversight._execute(
        database_url,
        f"INSERT INTO {TABLE} ({columns}, joined_at) VALUES ({placeholders}, now())",
        *row.values(),
    )
    return visit_id


def _refused(database_url: str, error: type[Exception], constraint: str, **values):
    with pytest.raises(error) as refused:
        _visit(database_url, **values)
    assert refused.value.diag.constraint_name == constraint


def test_upgrade_adds_the_visit_table_and_downgrade_restores_the_parent(
    database: str, postgres: PostgresContainer
):
    config = expand._alembic_config(database)
    parent_schema = widget_migrations._schema(postgres)
    user_id, space_id, _ = oversight._seed(database)
    (tenant_id,) = widget_migrations._fetch(
        database, "SELECT tenant_id FROM spaces WHERE id = %s", space_id
    )[0]

    command.upgrade(config, VISITS)

    assert oversight._columns(database, TABLE) == {
        "id": "NO",
        "tenant_id": "NO",
        "space_id": "NO",
        "user_id": "YES",
        "role": "NO",
        "reason": "NO",
        "joined_at": "NO",
        "left_at": "YES",
    }
    assert oversight._constraints(database, TABLE) == {
        "ck_space_oversight_visits_reason_length": "c",
        "ck_space_oversight_visits_left_after_joined": "c",
        # Visits go with their tenant and space, and forget a deleted user.
        "space_oversight_visits_tenant_id_fkey": "fk:c",
        "space_oversight_visits_space_id_fkey": "fk:c",
        "space_oversight_visits_user_id_fkey": "fk:n",
    }
    assert widget_migrations._fetch(
        database,
        "SELECT indexname::text FROM pg_indexes WHERE tablename = %s"
        " AND indexdef LIKE '%%UNIQUE%%' AND indexdef LIKE '%%left_at IS NULL%%'",
        TABLE,
    ) == [("uq_space_oversight_visits_open",)]

    scope = {"tenant_id": tenant_id, "space_id": space_id}
    _refused(
        database,
        errors.CheckViolation,
        "ck_space_oversight_visits_reason_length",
        **scope,
        user_id=user_id,
        reason="kort",
    )
    ended = _visit(database, **scope, user_id=user_id)
    oversight._execute(
        database, f"UPDATE {TABLE} SET left_at = now() WHERE id = %s", ended
    )
    with pytest.raises(errors.CheckViolation) as refused:
        oversight._execute(
            database,
            f"UPDATE {TABLE} SET left_at = joined_at - interval '1 minute'"
            " WHERE id = %s",
            ended,
        )
    assert (
        refused.value.diag.constraint_name
        == "ck_space_oversight_visits_left_after_joined"
    )
    _visit(database, **scope, user_id=user_id)
    # One open visit per person and space: the one a leave closes.
    _refused(
        database,
        errors.UniqueViolation,
        "uq_space_oversight_visits_open",
        **scope,
        user_id=user_id,
    )

    oversight._execute(database, "DELETE FROM users WHERE id = %s", user_id)
    assert widget_migrations._fetch(
        database, f"SELECT count(*), count(user_id) FROM {TABLE}"
    ) == [(2, 0)]
    visits_schema = widget_migrations._schema(postgres)

    command.downgrade(config, PARENT)

    assert widget_migrations._schema(postgres) == parent_schema
    assert widget_migrations._fetch(
        database, "SELECT name FROM spaces WHERE id = %s", space_id
    ) == [("Bygglov",)]

    command.upgrade(config, VISITS)
    assert widget_migrations._schema(postgres) == visits_schema


def test_visits_go_with_their_space(database: str):
    config = expand._alembic_config(database)
    user_id, space_id, _ = oversight._seed(database)
    (tenant_id,) = widget_migrations._fetch(
        database, "SELECT tenant_id FROM spaces WHERE id = %s", space_id
    )[0]
    command.upgrade(config, VISITS)
    _visit(database, tenant_id=tenant_id, space_id=space_id, user_id=user_id)

    oversight._execute(database, "DELETE FROM spaces WHERE id = %s", space_id)

    assert widget_migrations._fetch(database, f"SELECT count(*) FROM {TABLE}") == [(0,)]


def test_upgrade_gives_up_instead_of_queueing_behind_a_writer(database: str):
    """The foreign keys lock spaces against writes while they are created;
    behind a request transaction that wrote a space the revision must fail
    fast rather than stall every space write queued behind it."""
    config = expand._alembic_config(database)
    executor = ThreadPoolExecutor(max_workers=1)
    with closing(expand._connect(database)) as blocker:
        try:
            with blocker.cursor() as cursor:
                cursor.execute("LOCK TABLE spaces IN ROW EXCLUSIVE MODE")
            upgrade = executor.submit(command.upgrade, config, VISITS)
            with pytest.raises(Exception, match="lock timeout"):
                upgrade.result(timeout=60)
        finally:
            blocker.rollback()
            executor.shutdown(wait=True)
    assert widget_migrations._fetch(
        database, "SELECT version_num FROM alembic_version"
    ) == [(PARENT,)]
    command.upgrade(config, VISITS)
