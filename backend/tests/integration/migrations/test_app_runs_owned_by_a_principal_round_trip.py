from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.migration_isolation]

REVISION = "202611251200"
PRE_REVISION = "202611251100"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def encryption_service() -> Generator[None, None, None]:
    yield


@pytest.fixture
def migration_db() -> Generator[tuple[Any, Config], None, None]:
    """A database of its own: the shared one is already at head, where an
    upgrade to the earlier revision changes nothing."""
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="app_run_owner",
        password="app_run_owner_password",
        dbname="app_run_owner",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        backend_dir = Path(__file__).resolve().parents[3]
        config = Config(str(backend_dir / "alembic.ini"))
        config.set_main_option("script_location", str(backend_dir / "alembic"))
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, PRE_REVISION)
        connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
        connection.autocommit = True
        try:
            yield connection, config
        finally:
            connection.close()


def _owner_schema(connection) -> dict[str, object]:
    """Whether a run needs a person, what removing an owner does to it ('n'
    is SET NULL, 'r' is RESTRICT), and the check on its owners."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'app_runs' AND column_name IN"
            " ('user_id', 'service_principal_id')"
        )
        nullable = dict(cursor.fetchall())
        cursor.execute(
            """
            SELECT att.attname, ref.relname, con.confdeltype
            FROM pg_constraint AS con
            JOIN pg_attribute AS att
              ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
            JOIN pg_class AS ref ON ref.oid = con.confrelid
            WHERE con.contype = 'f'
              AND con.conrelid = 'app_runs'::regclass
              AND att.attname IN ('user_id', 'service_principal_id')
            """
        )
        keys = sorted(cursor.fetchall())
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE contype = 'c'"
            " AND conrelid = 'app_runs'::regclass AND conname LIKE 'ck_app_runs_%'"
        )
        checks = sorted(row[0] for row in cursor.fetchall())
    return {"nullable": nullable, "keys": keys, "checks": checks}


_BEFORE = {
    "nullable": {"user_id": "NO"},
    "keys": [("user_id", "users", "n")],
    "checks": [],
}
_AFTER = {
    "nullable": {"user_id": "YES", "service_principal_id": "YES"},
    "keys": [
        ("service_principal_id", "service_principals", "r"),
        ("user_id", "users", "n"),
    ],
    "checks": ["ck_app_runs_single_owner"],
}


def test_a_run_may_belong_to_a_person_or_a_service_principal(migration_db) -> None:
    connection, config = migration_db
    assert _owner_schema(connection) == _BEFORE

    command.upgrade(config, REVISION)

    assert _owner_schema(connection) == _AFTER


def test_downgrade_requires_a_person_again_and_upgrade_frees_it(migration_db) -> None:
    connection, config = migration_db
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    assert _owner_schema(connection) == _BEFORE

    command.upgrade(config, REVISION)

    assert _owner_schema(connection) == _AFTER
