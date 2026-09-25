"""Revision 202609241000: the oversight join marker and widget activation
requests. Additive and reversible: the columns arrive empty, their CHECK
constraints hold, and a downgrade restores the widgets head exactly while
keeping every row."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import errors
from sqlalchemy import create_engine
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand
from tests.integration.migrations import test_widget_migrations as widget_migrations

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PARENT = widget_migrations.WIDGET_HEAD
OVERSIGHT = "202609241000"
REASON = "Ärende KS 2026/123 – kontroll av underlag"

CHECKS = {
    "spaces_users": {
        "ck_spaces_users_oversight_join_pair",
        "ck_spaces_users_oversight_join_reason_length",
    },
    "widgets": {
        "ck_widgets_activation_request_status",
        "ck_widgets_activation_decline_pair",
        "ck_widgets_activation_request_xor_decline",
        "ck_widgets_activation_decline_reason_length",
    },
}
COLUMNS = {
    "spaces_users": {"oversight_joined_at", "oversight_join_reason"},
    "widgets": {
        "activation_requested_at",
        "activation_requested_by_user_id",
        "activation_declined_at",
        "activation_declined_by_user_id",
        "activation_decline_reason",
    },
}


@pytest.fixture(scope="module")
def postgres() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="oversight_migration",
        password="oversight_migration_password",
        dbname="oversight_migration",
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


def _execute(database_url: str, query: str, *params: object) -> None:
    with closing(widget_migrations._autocommit(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)


def _columns(database_url: str, table: str) -> dict[str, str]:
    return dict(
        widget_migrations._fetch(
            database_url,
            "SELECT column_name::text, is_nullable::text"
            " FROM information_schema.columns WHERE table_name = %s",
            table,
        )
    )


def _constraints(database_url: str, table: str) -> dict[str, str]:
    """CHECK and foreign-key constraints of ``table``: name -> kind, with
    the ON DELETE action for foreign keys."""
    return dict(
        widget_migrations._fetch(
            database_url,
            "SELECT conname::text,"
            " CASE contype WHEN 'f' THEN 'fk:' || confdeltype ELSE contype::text END"
            " FROM pg_constraint WHERE conrelid = %s::regclass"
            " AND contype IN ('c', 'f')",
            table,
        )
    )


def _seed(database_url: str) -> tuple[str, str, str]:
    """A shared space with a member and a draft widget, written at the
    parent revision: (user id, space id, widget id)."""
    tenant_id, user_id = widget_migrations._seed_tenant_and_user(database_url)
    space_id, widget_id = str(uuid4()), str(uuid4())
    _execute(
        database_url,
        "INSERT INTO spaces (id, name, tenant_id) VALUES (%s, 'Bygglov', %s)",
        space_id,
        tenant_id,
    )
    _execute(
        database_url,
        "INSERT INTO spaces_users (space_id, user_id, role) VALUES (%s, %s, 'admin')",
        space_id,
        user_id,
    )
    _execute(
        database_url,
        "INSERT INTO widgets (id, public_id, tenant_id, space_id, target_type,"
        " target_id, name) VALUES (%s, %s, %s, %s, 'assistant', %s, 'Webbchatt')",
        widget_id,
        f"wgt_{widget_id[:8]}",
        tenant_id,
        space_id,
        str(uuid4()),
    )
    return user_id, space_id, widget_id


def _refused(database_url: str, constraint: str, query: str, *params: object) -> None:
    with pytest.raises(errors.CheckViolation) as refused:
        _execute(database_url, query, *params)
    assert refused.value.diag.constraint_name == constraint


def test_upgrade_adds_nullable_columns_and_checks_and_downgrade_restores_the_parent(
    database: str, postgres: PostgresContainer
):
    config = expand._alembic_config(database)
    parent_schema = widget_migrations._schema(postgres)
    user_id, space_id, widget_id = _seed(database)

    command.upgrade(config, OVERSIGHT)

    for table, columns in COLUMNS.items():
        present = _columns(database, table)
        assert {column: present.get(column) for column in columns} == {
            column: "YES" for column in columns
        }, table
        constraints = _constraints(database, table)
        assert CHECKS[table] <= {
            name for name, kind in constraints.items() if kind == "c"
        }
    widget_constraints = _constraints(database, "widgets")
    # Deleting the requester or decliner keeps the widget and forgets who.
    assert widget_constraints["fk_widgets_activation_requested_by_user_id"] == "fk:n"
    assert widget_constraints["fk_widgets_activation_declined_by_user_id"] == "fk:n"
    assert widget_migrations._fetch(
        database,
        "SELECT oversight_joined_at, oversight_join_reason FROM spaces_users"
        " WHERE space_id = %s",
        space_id,
    ) == [(None, None)]
    assert widget_migrations._fetch(
        database,
        "SELECT activation_requested_at, activation_declined_at FROM widgets"
        " WHERE id = %s",
        widget_id,
    ) == [(None, None)]

    _refused(
        database,
        "ck_spaces_users_oversight_join_pair",
        "UPDATE spaces_users SET oversight_joined_at = now() WHERE space_id = %s",
        space_id,
    )
    _refused(
        database,
        "ck_spaces_users_oversight_join_reason_length",
        "UPDATE spaces_users SET oversight_joined_at = now(),"
        " oversight_join_reason = 'kort' WHERE space_id = %s",
        space_id,
    )
    for constraint, assignments in (
        (
            "ck_widgets_activation_request_status",
            "status = 'active', activated_at = now(), activation_requested_at = now()",
        ),
        ("ck_widgets_activation_decline_pair", "activation_decline_reason = %s"),
        (
            "ck_widgets_activation_request_xor_decline",
            "activation_requested_at = now(), activation_declined_at = now(),"
            " activation_decline_reason = %s",
        ),
        (
            "ck_widgets_activation_decline_reason_length",
            "activation_declined_at = now(), activation_decline_reason = 'kort'",
        ),
    ):
        params: tuple[object, ...] = (REASON,) if "%s" in assignments else ()
        _refused(
            database,
            constraint,
            f"UPDATE widgets SET {assignments} WHERE id = %s",
            *params,
            widget_id,
        )

    _execute(
        database,
        "UPDATE spaces_users SET oversight_joined_at = now(),"
        " oversight_join_reason = %s WHERE space_id = %s",
        REASON,
        space_id,
    )
    _execute(
        database,
        "UPDATE widgets SET activation_requested_at = now(),"
        " activation_requested_by_user_id = %s WHERE id = %s",
        user_id,
        widget_id,
    )
    oversight_schema = widget_migrations._schema(postgres)

    command.downgrade(config, PARENT)

    assert widget_migrations._schema(postgres) == parent_schema
    assert widget_migrations._fetch(
        database, "SELECT role FROM spaces_users WHERE space_id = %s", space_id
    ) == [("admin",)]
    assert widget_migrations._fetch(
        database, "SELECT status FROM widgets WHERE id = %s", widget_id
    ) == [("draft",)]

    command.upgrade(config, OVERSIGHT)
    assert widget_migrations._schema(postgres) == oversight_schema
    assert widget_migrations._fetch(
        database,
        "SELECT oversight_join_reason FROM spaces_users WHERE space_id = %s",
        space_id,
    ) == [(None,)]


def test_upgrade_gives_up_instead_of_queueing_behind_a_long_transaction(
    database: str,
):
    """The revision takes a lock on spaces_users and widgets; with a reader
    holding one open it must fail fast rather than stall every space read
    queued behind it. Run in a worker with a bound, so a lost timeout fails
    the test instead of hanging the migration job."""
    config = expand._alembic_config(database)
    executor = ThreadPoolExecutor(max_workers=1)
    with closing(psycopg2.connect(database.replace("+psycopg2", ""))) as blocker:
        try:
            with blocker.cursor() as cursor:
                cursor.execute("SELECT 1 FROM widgets FOR UPDATE")
            upgrade = executor.submit(command.upgrade, config, OVERSIGHT)
            with pytest.raises(Exception, match="lock timeout"):
                upgrade.result(timeout=60)
        finally:
            blocker.rollback()
            executor.shutdown(wait=True)
    assert widget_migrations._fetch(
        database, "SELECT version_num FROM alembic_version"
    ) == [(PARENT,)]
    command.upgrade(config, OVERSIGHT)


def test_upgrade_hands_back_the_default_lock_timeout(database: str):
    """Revisions after this one run in the same transaction and must not
    inherit its short timeout."""
    config = expand._alembic_config(database)
    migration = ScriptDirectory.from_config(config).get_revision(OVERSIGHT).module
    engine = create_engine(database)
    try:
        with engine.connect() as connection:
            # One transaction, as alembic runs every pending revision.
            default = connection.exec_driver_sql("SHOW lock_timeout").scalar()
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            after = connection.exec_driver_sql("SHOW lock_timeout").scalar()
            connection.rollback()
    finally:
        engine.dispose()
    assert default != "5s"
    assert after == default
