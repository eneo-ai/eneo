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

REVISION = "202611241000"
PRE_REVISION = "202611201305"


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
        username="service_principals",
        password="service_principals_password",
        dbname="service_principals",
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
            (tenant_id, f"service-principals-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _key(
    connection,
    *,
    tenant_id: str,
    creator_id: str,
    ownership: str,
    name: str,
    description: str | None = None,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    rotated_from: str | None = None,
    state: str = "active",
    service_principal_id: str | None = None,
    with_principal_column: bool = False,
) -> str:
    key_id = str(uuid4())
    columns = [
        "id",
        "tenant_id",
        "ownership",
        "owner_user_id",
        "created_by_user_id",
        "scope_type",
        "scope_id",
        "permission",
        "key_type",
        "key_hash",
        "hash_version",
        "key_prefix",
        "key_suffix",
        "name",
        "description",
        "state",
        "rotated_from_key_id",
    ]
    values: list[object] = [
        key_id,
        tenant_id,
        ownership,
        creator_id if ownership == "user" else None,
        creator_id,
        scope_type,
        scope_id,
        "read",
        "sk_",
        f"hash-{key_id}",
        "hmac-sha256-v1",
        "sk_",
        key_id[-4:],
        name,
        description,
        state,
        rotated_from,
    ]
    if with_principal_column:
        columns.append("service_principal_id")
        values.append(service_principal_id)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO api_keys_v2 ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            values,
        )
    return key_id


def _principal_of(connection, key_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT service_principal_id FROM api_keys_v2 WHERE id = %s", (key_id,)
        )
        value = cursor.fetchone()[0]
    return None if value is None else str(value)


def _principal(connection, principal_id: str) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id, display_name, description, scope_type, scope_id, state,"
            " created_by_user_id, disabled_at FROM service_principals WHERE id = %s",
            (principal_id,),
        )
        row = cursor.fetchone()
    return {
        "tenant_id": str(row[0]),
        "display_name": row[1],
        "description": row[2],
        "scope_type": row[3],
        "scope_id": None if row[4] is None else str(row[4]),
        "state": row[5],
        "created_by_user_id": str(row[6]),
        "disabled_at": row[7],
    }


def _principal_count(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM service_principals")
        return cursor.fetchone()[0]


def test_every_key_in_a_rotation_chain_gets_the_same_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    first = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Invoice reader",
        description="Reads invoices",
        state="revoked",
    )
    second = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Invoice reader, rotated",
        rotated_from=first,
        state="revoked",
    )
    third = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Invoice reader, rotated twice",
        rotated_from=second,
    )

    command.upgrade(config, REVISION)

    principal_id = _principal_of(connection, first)
    assert principal_id is not None
    assert _principal_of(connection, second) == principal_id
    assert _principal_of(connection, third) == principal_id
    assert _principal_count(connection) == 1
    assert _principal(connection, principal_id) == {
        "tenant_id": tenant_id,
        "display_name": "Invoice reader",
        "description": "Reads invoices",
        "scope_type": "tenant",
        "scope_id": None,
        "state": "active",
        "created_by_user_id": user_id,
        "disabled_at": None,
    }


def test_separate_service_keys_get_separate_principals_in_their_own_tenant(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    other_tenant_id, other_user_id = _tenant_with_user(connection)
    space_id = str(uuid4())
    tenant_key = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Tenant key",
    )
    space_key = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Space key",
        scope_type="space",
        scope_id=space_id,
    )
    other_key = _key(
        connection,
        tenant_id=other_tenant_id,
        creator_id=other_user_id,
        ownership="service",
        name="Other tenant key",
    )

    command.upgrade(config, REVISION)

    principals = {
        key: _principal_of(connection, key)
        for key in (tenant_key, space_key, other_key)
    }
    assert None not in principals.values()
    assert len(set(principals.values())) == 3
    space_principal = _principal(connection, str(principals[space_key]))
    assert space_principal["scope_type"] == "space"
    assert space_principal["scope_id"] == space_id
    assert _principal(connection, str(principals[other_key]))["tenant_id"] == (
        other_tenant_id
    )


def test_user_keys_get_no_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    user_key = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="user",
        name="Personal key",
    )

    command.upgrade(config, REVISION)

    assert _principal_of(connection, user_key) is None
    assert _principal_count(connection) == 0


def test_a_service_key_cannot_be_stored_without_a_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    command.upgrade(config, REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation):
        _key(
            connection,
            tenant_id=tenant_id,
            creator_id=user_id,
            ownership="service",
            name="No principal",
        )


def test_a_user_key_cannot_carry_a_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    existing = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Service key",
    )
    command.upgrade(config, REVISION)
    principal_id = _principal_of(connection, existing)

    with pytest.raises(psycopg2.errors.CheckViolation):
        _key(
            connection,
            tenant_id=tenant_id,
            creator_id=user_id,
            ownership="user",
            name="User key with a principal",
            service_principal_id=principal_id,
            with_principal_column=True,
        )


def test_a_principal_cannot_be_deleted_while_a_key_points_at_it(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    key_id = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Service key",
    )
    command.upgrade(config, REVISION)
    principal_id = _principal_of(connection, key_id)

    with (
        pytest.raises(psycopg2.errors.ForeignKeyViolation),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))


def test_downgrade_removes_the_principals_and_upgrade_derives_them_again(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    first = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Service key",
    )
    second = _key(
        connection,
        tenant_id=tenant_id,
        creator_id=user_id,
        ownership="service",
        name="Service key, rotated",
        rotated_from=first,
    )
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.service_principals')")
        assert cursor.fetchone()[0] is None
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'api_keys_v2' AND column_name = 'service_principal_id'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM api_keys_v2 WHERE id IN (%s, %s)", (first, second)
        )
        assert cursor.fetchone()[0] == 2

    command.upgrade(config, REVISION)

    principal_id = _principal_of(connection, first)
    assert principal_id is not None
    assert _principal_of(connection, second) == principal_id
    assert _principal_count(connection) == 1
