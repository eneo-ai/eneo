"""Widget revisions: online on the chat tables and reversible to develop's head.

202609231701 changes `sessions` and `questions`, two of the largest tables in a
deployment. Chat writes must keep flowing while it scans them, and a downgrade
must restore develop's schema exactly.
"""

from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from time import monotonic, sleep
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

DEVELOP_HEAD = "202609231001"
WIDGET_HEAD = "202609231701"
_MIGRATION_APPLICATION = "widget-migration-under-test"


@pytest.fixture(scope="module")
def postgres() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="widget_migration",
        password="widget_migration_password",
        dbname="widget_migration",
    ) as container:
        command.upgrade(
            expand._alembic_config(container.get_connection_url()), DEVELOP_HEAD
        )
        yield container


@pytest.fixture
def database(postgres: PostgresContainer) -> Generator[str, None, None]:
    database_url = postgres.get_connection_url()
    try:
        yield database_url
    finally:
        command.downgrade(expand._alembic_config(database_url), DEVELOP_HEAD)


def _autocommit(database_url: str):
    connection = expand._connect(database_url)
    connection.autocommit = True
    return connection


def _fetch(database_url: str, query: str, *params) -> list[tuple]:
    with closing(_autocommit(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()


def _schema(postgres: PostgresContainer) -> str:
    result = postgres.exec(
        [
            "pg_dump",
            "--username",
            postgres.username,
            "--dbname",
            postgres.dbname,
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--exclude-table=alembic_version",
        ]
    )
    assert result.exit_code == 0, result.output.decode()
    # pg_dump writes a random \restrict key into every dump.
    return "\n".join(
        line
        for line in result.output.decode().splitlines()
        if not line.startswith(("\\restrict", "\\unrestrict"))
    )


def _seed_tenant_and_user(database_url: str) -> tuple[str, str]:
    tenant_id, user_id = str(uuid4()), str(uuid4())
    with closing(_autocommit(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, quota_limit, state) "
                "VALUES (%s, %s, 1000000, 'active')",
                (tenant_id, f"widget-migration-{tenant_id}"),
            )
            cursor.execute(
                "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
                "VALUES (%s, %s, 'member', %s, 0, 'active')",
                (user_id, tenant_id, f"{user_id}@example.test"),
            )
    return tenant_id, user_id


def _wait_until_blocked_by(database_url: str, blocker_pid: int, upgrade: Future) -> int:
    deadline = monotonic() + 60
    while monotonic() < deadline:
        if upgrade.done():
            upgrade.result()
            pytest.fail("the upgrade finished without waiting for the chat write")
        waiting = _fetch(
            database_url,
            "SELECT pid FROM pg_stat_activity "
            "WHERE application_name = %s AND %s = ANY(pg_blocking_pids(pid))",
            _MIGRATION_APPLICATION,
            blocker_pid,
        )
        if waiting:
            return waiting[0][0]
        sleep(0.05)
    pytest.fail("the upgrade never waited for the in-flight chat write")


def test_upgrade_keeps_chat_writes_flowing_while_it_waits_on_a_writer(database):
    tenant_id, user_id = _seed_tenant_and_user(database)
    migration_config = expand._alembic_config(
        f"{database}?application_name={_MIGRATION_APPLICATION}"
    )
    # An in-flight chat write that the question index build has to wait for.
    blocker = expand._connect(database)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with blocker.cursor() as cursor:
            cursor.execute("LOCK TABLE questions IN ROW EXCLUSIVE MODE")
            cursor.execute("SELECT pg_backend_pid()")
            (blocker_pid,) = cursor.fetchone()
        upgrade = executor.submit(command.upgrade, migration_config, WIDGET_HEAD)
        migration_pid = _wait_until_blocked_by(database, blocker_pid, upgrade)

        with closing(_autocommit(database)) as writer:
            with writer.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute(
                    "INSERT INTO sessions (user_id, name) "
                    "VALUES (%s, 'during upgrade') RETURNING id",
                    (user_id,),
                )
                (session_id,) = cursor.fetchone()
                cursor.execute(
                    "INSERT INTO questions (question, answer, num_tokens_question, "
                    "num_tokens_answer, tenant_id, session_id) "
                    "VALUES ('q', 'a', 1, 1, %s, %s) RETURNING id",
                    (tenant_id, session_id),
                )
                (question_id,) = cursor.fetchone()
                cursor.execute("DELETE FROM questions WHERE id = %s", (question_id,))

        still_waiting = _fetch(database, "SELECT pg_blocking_pids(%s)", migration_pid)[
            0
        ][0]
        assert blocker_pid in still_waiting
    finally:
        blocker.rollback()
        blocker.close()
        executor.shutdown(wait=True)
    upgrade.result()

    assert (
        _fetch(
            database,
            "SELECT conname::text FROM pg_constraint "
            "WHERE conrelid = 'sessions'::regclass AND NOT convalidated "
            "UNION ALL "
            "SELECT indexrelid::regclass::text FROM pg_index "
            "WHERE indrelid IN ('sessions'::regclass, 'questions'::regclass) "
            "AND NOT (indisvalid AND indisready)",
        )
        == []
    )
    assert _fetch(
        database,
        "SELECT tgname::text FROM pg_trigger WHERE tgrelid = 'questions'::regclass "
        "AND tgname = 'delete_question_owned_log'",
    ) == [("delete_question_owned_log",)]


def test_downgrade_restores_develop_schema_and_drops_widget_state(database, postgres):
    config = expand._alembic_config(database)
    develop_schema = _schema(postgres)
    tenant_id, user_id = _seed_tenant_and_user(database)
    with closing(_autocommit(database)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO roles (name, permissions, tenant_id, predefined_source) "
                "VALUES ('Owner', ARRAY['admin']::varchar[], %s, 'Owner'), "
                "('Custom', ARRAY['assistants']::varchar[], %s, NULL)",
                (tenant_id, tenant_id),
            )

    command.upgrade(config, WIDGET_HEAD)
    widget_schema = _schema(postgres)
    with closing(_autocommit(database)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE roles SET permissions = array_append(permissions, 'widgets') "
                "WHERE name = 'Custom'"
            )
            cursor.execute(
                "INSERT INTO spaces (name, tenant_id) VALUES ('Public', %s) "
                "RETURNING id",
                (tenant_id,),
            )
            (space_id,) = cursor.fetchone()
            cursor.execute(
                "INSERT INTO widgets (public_id, tenant_id, space_id, target_type, "
                "target_id, name) VALUES ('wdg_migration', %s, %s, 'assistant', %s, "
                "'Help') RETURNING id",
                (tenant_id, space_id, str(uuid4())),
            )
            (widget_id,) = cursor.fetchone()
            cursor.execute(
                "INSERT INTO sessions (widget_id, visitor_id, name) "
                "VALUES (%s, %s, 'visitor')",
                (widget_id, str(uuid4())),
            )
            cursor.execute(
                "INSERT INTO sessions (user_id, name) VALUES (%s, 'member')",
                (user_id,),
            )
    roles = "SELECT name, permissions FROM roles WHERE tenant_id = %s ORDER BY name"
    assert _fetch(database, roles, tenant_id) == [
        ("Custom", ["assistants", "widgets"]),
        ("Owner", ["admin", "widgets"]),
    ]

    command.downgrade(config, DEVELOP_HEAD)

    assert _schema(postgres) == develop_schema
    assert _fetch(
        database, "SELECT name FROM sessions WHERE name IN ('visitor', 'member')"
    ) == [("member",)]
    assert _fetch(database, roles, tenant_id) == [
        ("Custom", ["assistants"]),
        ("Owner", ["admin"]),
    ]

    command.upgrade(config, WIDGET_HEAD)
    assert _schema(postgres) == widget_schema
