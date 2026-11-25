from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.migration_isolation]

REVISION = "202611251300"
PRE_REVISION = "202611251200"

TABLES = ("groups", "websites", "info_blobs")


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
        username="knowledge_creator",
        password="knowledge_creator_password",
        dbname="knowledge_creator",
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


def _tenant_with_user(connection) -> tuple[str, str]:
    tenant_id, user_id = str(uuid4()), str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state) "
            "VALUES (%s, %s, 1000000, 'active')",
            (tenant_id, f"knowledge-creator-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _collection(
    connection,
    *,
    tenant_id: str,
    user_id: str | None = None,
    created_by_service_id: str | None = None,
) -> str:
    collection_id = str(uuid4())
    columns: dict[str, object] = {
        "id": collection_id,
        "name": "Handbook",
        "size": 0,
        "tenant_id": tenant_id,
    }
    if user_id is not None:
        columns["user_id"] = user_id
    if created_by_service_id is not None:
        columns["created_by_service_id"] = created_by_service_id
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO groups ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            list(columns.values()),
        )
    return collection_id


def _service_principal(connection, *, tenant_id: str) -> str:
    principal_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO service_principals (id, tenant_id, display_name, scope_type) "
            "VALUES (%s, %s, 'Invoice reader', 'tenant')",
            (principal_id, tenant_id),
        )
    return principal_id


def _creator(connection, collection_id: str) -> tuple[str | None, str | None]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id, created_by_service_id FROM groups WHERE id = %s",
            (collection_id,),
        )
        row = cursor.fetchone()
    return tuple(None if value is None else str(value) for value in row)


def _creator_schema(connection, table: str) -> dict[str, object]:
    """Whether the creator may be empty, and what removing the person or the
    service principal does to the row ('n' is SET NULL, 'c' is CASCADE)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = %s AND column_name IN"
            " ('user_id', 'created_by_service_id')",
            (table,),
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
              AND con.conrelid = to_regclass(%s)
              AND att.attname IN ('user_id', 'created_by_service_id')
            """,
            (table,),
        )
        keys = sorted(cursor.fetchall())
    return {"nullable": nullable, "keys": keys}


@pytest.mark.parametrize("table", TABLES)
def test_the_creator_becomes_an_optional_trace(migration_db, table) -> None:
    connection, config = migration_db
    before = _creator_schema(connection, table)
    assert before["nullable"] == {"user_id": "NO"}

    command.upgrade(config, REVISION)

    assert _creator_schema(connection, table) == {
        "nullable": {"user_id": "YES", "created_by_service_id": "YES"},
        "keys": [
            ("created_by_service_id", "service_principals", "n"),
            ("user_id", "users", "n"),
        ],
    }


def test_existing_rows_keep_their_creator(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    collection_id = _collection(connection, tenant_id=tenant_id, user_id=user_id)

    command.upgrade(config, REVISION)

    assert _creator(connection, collection_id) == (user_id, None)


def test_a_row_can_be_made_by_a_service_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)

    collection_id = _collection(
        connection, tenant_id=tenant_id, created_by_service_id=principal_id
    )

    assert _creator(connection, collection_id) == (None, principal_id)


def test_removing_the_creator_keeps_the_collection(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    collection_id = _collection(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))

    assert _creator(connection, collection_id) == (None, None)


def test_downgrade_is_refused_while_a_row_has_no_person_as_creator(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    persons = _collection(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    services = _collection(
        connection, tenant_id=tenant_id, created_by_service_id=principal_id
    )

    with pytest.raises(RuntimeError, match="have no person as creator"):
        command.downgrade(config, PRE_REVISION)

    assert _creator(connection, services) == (None, principal_id)
    assert _creator(connection, persons) == (user_id, None)


@pytest.mark.parametrize("table", TABLES)
def test_downgrade_restores_the_required_creator_and_upgrade_frees_it_again(
    migration_db, table
) -> None:
    connection, config = migration_db
    before = _creator_schema(connection, table)
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    restored = _creator_schema(connection, table)
    assert restored == before
    assert restored == {
        "nullable": {"user_id": "NO"},
        "keys": [("user_id", "users", "c")],
    }

    command.upgrade(config, REVISION)

    assert _creator_schema(connection, table)["nullable"] == {
        "user_id": "YES",
        "created_by_service_id": "YES",
    }
