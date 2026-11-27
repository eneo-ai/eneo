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

REVISION = "202611241100"
PRE_REVISION = "202611241000"


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
        username="file_owner",
        password="file_owner_password",
        dbname="file_owner",
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
            (tenant_id, f"file-owner-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _file_before_upgrade(connection, *, tenant_id: str, user_id: str) -> str:
    file_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO files (id, name, mimetype, file_type, user_id, tenant_id) "
            "VALUES (%s, 'minutes.txt', 'text/plain', 'text', %s, %s)",
            (file_id, user_id, tenant_id),
        )
    return file_id


def _service_principal(connection, *, tenant_id: str) -> str:
    principal_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO service_principals (id, tenant_id, display_name, scope_type) "
            "VALUES (%s, %s, 'Invoice reader', 'tenant')",
            (principal_id, tenant_id),
        )
    return principal_id


def _file_after_upgrade(
    connection,
    *,
    tenant_id: str,
    owner_type: str,
    owner_user_id: str | None = None,
    owner_service_id: str | None = None,
) -> str:
    file_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO files (id, name, mimetype, file_type, owner_type,"
            " owner_user_id, owner_service_id, tenant_id) "
            "VALUES (%s, 'invoice.txt', 'text/plain', 'text', %s, %s, %s, %s)",
            (file_id, owner_type, owner_user_id, owner_service_id, tenant_id),
        )
    return file_id


def _owner(connection, file_id: str) -> tuple[str, str | None, str | None]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT owner_type, owner_user_id, owner_service_id FROM files"
            " WHERE id = %s",
            (file_id,),
        )
        owner_type, user_id, service_id = cursor.fetchone()
    return (
        owner_type,
        None if user_id is None else str(user_id),
        None if service_id is None else str(service_id),
    )


def _file_columns(connection) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'files'"
        )
        return dict(cursor.fetchall())


def _file_exists(connection, file_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM files WHERE id = %s", (file_id,))
        return cursor.fetchone()[0] == 1


def test_every_existing_file_stays_its_persons_file(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file_before_upgrade(connection, tenant_id=tenant_id, user_id=user_id)

    command.upgrade(config, REVISION)

    assert _owner(connection, file_id) == ("user", user_id, None)
    columns = _file_columns(connection)
    assert "user_id" not in columns
    assert columns["owner_type"] == "NO"
    assert columns["owner_user_id"] == "YES"
    assert columns["owner_service_id"] == "YES"


def test_a_file_can_be_owned_by_a_service_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)

    file_id = _file_after_upgrade(
        connection,
        tenant_id=tenant_id,
        owner_type="service_key",
        owner_service_id=principal_id,
    )

    assert _owner(connection, file_id) == ("service_key", None, principal_id)


@pytest.mark.parametrize(
    "owner",
    [
        {"owner_type": "user"},
        {"owner_type": "service_key"},
        {"owner_type": "user", "service": True},
        {"owner_type": "service_key", "user": True},
        {"owner_type": "user", "user": True, "service": True},
        {"owner_type": "space", "user": True},
    ],
    ids=[
        "person without an id",
        "service without an id",
        "person named by a service id",
        "service named by a user id",
        "both ids",
        "unknown owner type",
    ],
)
def test_a_file_must_name_exactly_the_owner_of_its_type(migration_db, owner) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)

    with pytest.raises(psycopg2.errors.CheckViolation):
        _file_after_upgrade(
            connection,
            tenant_id=tenant_id,
            owner_type=owner["owner_type"],
            owner_user_id=user_id if owner.get("user") else None,
            owner_service_id=principal_id if owner.get("service") else None,
        )


def test_removing_an_owner_no_longer_removes_its_files(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    persons_file = _file_before_upgrade(
        connection, tenant_id=tenant_id, user_id=user_id
    )
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    services_file = _file_after_upgrade(
        connection,
        tenant_id=tenant_id,
        owner_type="service_key",
        owner_service_id=principal_id,
    )

    with (
        pytest.raises(psycopg2.errors.ForeignKeyViolation),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    with (
        pytest.raises(psycopg2.errors.ForeignKeyViolation),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))

    assert _file_exists(connection, persons_file)
    assert _file_exists(connection, services_file)


def test_downgrade_is_refused_while_a_service_owns_a_file(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    persons_file = _file_before_upgrade(
        connection, tenant_id=tenant_id, user_id=user_id
    )
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    services_file = _file_after_upgrade(
        connection,
        tenant_id=tenant_id,
        owner_type="service_key",
        owner_service_id=principal_id,
    )

    with pytest.raises(RuntimeError, match="owned by a service principal"):
        command.downgrade(config, PRE_REVISION)

    assert _owner(connection, services_file) == ("service_key", None, principal_id)
    assert _owner(connection, persons_file) == ("user", user_id, None)


def test_downgrade_gives_the_person_column_back_and_upgrade_renames_it_again(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file_before_upgrade(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    columns = _file_columns(connection)
    assert columns["user_id"] == "NO"
    assert "owner_type" not in columns
    assert "owner_user_id" not in columns
    assert "owner_service_id" not in columns
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id FROM files WHERE id = %s", (file_id,))
        assert str(cursor.fetchone()[0]) == user_id

    command.upgrade(config, REVISION)

    assert _owner(connection, file_id) == ("user", user_id, None)


def test_an_organisation_is_still_deleted_with_everything_it_owns(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    persons_file = _file_before_upgrade(
        connection, tenant_id=tenant_id, user_id=user_id
    )
    command.upgrade(config, REVISION)
    principal_id = _service_principal(connection, tenant_id=tenant_id)
    services_file = _file_after_upgrade(
        connection,
        tenant_id=tenant_id,
        owner_type="service_key",
        owner_service_id=principal_id,
    )

    key_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO api_keys_v2 (id, tenant_id, ownership, service_principal_id,"
            " scope_type, permission, key_type, key_hash, hash_version, key_prefix,"
            " key_suffix, name, state) VALUES (%s, %s, 'service', %s, 'tenant',"
            " 'read', 'sk_', %s, 'hmac_sha256', 'sk_', 'abcd', 'Invoice reader',"
            " 'active')",
            (key_id, tenant_id, principal_id, f"hash-{key_id}"),
        )

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))

    assert not _file_exists(connection, persons_file)
    assert not _file_exists(connection, services_file)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM users WHERE id = %s", (user_id,))
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM service_principals WHERE id = %s", (principal_id,)
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT count(*) FROM api_keys_v2 WHERE id = %s", (key_id,))
        assert cursor.fetchone()[0] == 0
