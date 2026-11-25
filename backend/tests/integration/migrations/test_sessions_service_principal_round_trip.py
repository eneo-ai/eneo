from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.migration_isolation]

REVISION = "202611241200"
PRE_REVISION = "202611241100"


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
        username="session_principal",
        password="session_principal_password",
        dbname="session_principal",
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
            (tenant_id, f"session-principal-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _service_principal(connection, *, tenant_id: str) -> str:
    principal_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO service_principals (id, tenant_id, display_name, scope_type) "
            "VALUES (%s, %s, 'Invoice reader', 'tenant')",
            (principal_id, tenant_id),
        )
    return principal_id


def _key(
    connection,
    *,
    tenant_id: str,
    service_principal_id: str | None = None,
    owner_user_id: str | None = None,
    rotated_from: str | None = None,
) -> str:
    key_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO api_keys_v2 (id, tenant_id, ownership, owner_user_id,"
            " service_principal_id, scope_type, permission, key_type, key_hash,"
            " hash_version, key_prefix, key_suffix, name, state, rotated_from_key_id)"
            " VALUES (%s, %s, %s, %s, %s, 'tenant', 'read', 'sk_', %s, 'hmac_sha256',"
            " 'sk_', 'abcd', 'Invoice reader', 'active', %s)",
            (
                key_id,
                tenant_id,
                "service" if service_principal_id else "user",
                owner_user_id,
                service_principal_id,
                f"hash-{key_id}",
                rotated_from,
            ),
        )
    return key_id


def _session(connection, **columns: str | None) -> str:
    session_id = str(uuid4())
    names = ["id", "name", *columns]
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO sessions ({', '.join(names)}) "
            f"VALUES ({', '.join(['%s'] * len(names))})",
            [session_id, "Conversation", *columns.values()],
        )
    return session_id


def _owner(connection, session_id: str) -> tuple[str | None, str | None, str | None]:
    """(user, service principal, key) of a conversation."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id, service_principal_id, api_key_id FROM sessions"
            " WHERE id = %s",
            (session_id,),
        )
        row = cursor.fetchone()
    return tuple(None if value is None else str(value) for value in row)


def test_a_service_keys_conversations_move_to_its_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    first_key = _key(connection, tenant_id=tenant_id, service_principal_id=principal_id)
    rotated_key = _key(
        connection,
        tenant_id=tenant_id,
        service_principal_id=principal_id,
        rotated_from=first_key,
    )
    before_rotation = _session(connection, api_key_id=first_key)
    after_rotation = _session(connection, api_key_id=rotated_key)
    persons = _session(connection, user_id=user_id)

    command.upgrade(config, REVISION)

    assert _owner(connection, before_rotation) == (None, principal_id, first_key)
    assert _owner(connection, after_rotation) == (None, principal_id, rotated_key)
    assert _owner(connection, persons) == (user_id, None, None)


def test_upgrade_is_refused_when_a_conversation_names_a_key_without_a_principal(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    personal_key = _key(connection, tenant_id=tenant_id, owner_user_id=user_id)
    session_id = _session(connection, api_key_id=personal_key)

    with pytest.raises(DBAPIError, match="has no service principal"):
        command.upgrade(config, REVISION)

    with connection.cursor() as cursor:
        cursor.execute("SELECT api_key_id FROM sessions WHERE id = %s", (session_id,))
        assert str(cursor.fetchone()[0]) == personal_key


def test_a_conversation_has_exactly_one_owner(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    key_id = _key(connection, tenant_id=tenant_id, service_principal_id=principal_id)
    command.upgrade(config, REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation):
        _session(connection)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _session(connection, user_id=user_id, service_principal_id=principal_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _session(connection, api_key_id=key_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _session(connection, user_id=user_id, api_key_id=key_id)

    without_a_key = _session(connection, service_principal_id=principal_id)
    assert _owner(connection, without_a_key) == (None, principal_id, None)


def test_removing_a_key_leaves_its_conversations_with_the_principal(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    key_id = _key(connection, tenant_id=tenant_id, service_principal_id=principal_id)
    session_id = _session(connection, api_key_id=key_id)
    command.upgrade(config, REVISION)

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM api_keys_v2 WHERE id = %s", (key_id,))

    assert _owner(connection, session_id) == (None, principal_id, None)
    with (
        pytest.raises(psycopg2.errors.ForeignKeyViolation),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))


def test_downgrade_is_refused_while_a_conversation_has_lost_its_key(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    key_id = _key(connection, tenant_id=tenant_id, service_principal_id=principal_id)
    session_id = _session(connection, api_key_id=key_id)
    command.upgrade(config, REVISION)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM api_keys_v2 WHERE id = %s", (key_id,))

    with pytest.raises(RuntimeError, match="whose key has been removed"):
        command.downgrade(config, PRE_REVISION)

    assert _owner(connection, session_id) == (None, principal_id, None)


def test_downgrade_gives_the_key_its_conversations_back_and_upgrade_moves_them_again(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    key_id = _key(connection, tenant_id=tenant_id, service_principal_id=principal_id)
    services = _session(connection, api_key_id=key_id)
    persons = _session(connection, user_id=user_id)
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_name ="
            " 'sessions' AND column_name = 'service_principal_id'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT user_id, api_key_id FROM sessions WHERE id = %s", (services,)
        )
        assert cursor.fetchone() == (None, key_id)
        cursor.execute(
            "SELECT user_id, api_key_id FROM sessions WHERE id = %s", (persons,)
        )
        assert cursor.fetchone() == (user_id, None)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _session(connection)

    command.upgrade(config, REVISION)

    assert _owner(connection, services) == (None, principal_id, key_id)
    assert _owner(connection, persons) == (user_id, None, None)
