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

REVISION = "202611261000"
PRE_REVISION = "202611251300"


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
        username="file_home",
        password="file_home_password",
        dbname="file_home",
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
            (tenant_id, f"file-home-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _file(connection, *, tenant_id: str, user_id: str) -> str:
    file_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO files (id, name, mimetype, file_type, owner_type,"
            " owner_user_id, tenant_id) "
            "VALUES (%s, 'minutes.txt', 'text/plain', 'text', 'user', %s, %s)",
            (file_id, user_id, tenant_id),
        )
    return file_id


def _space(connection, *, tenant_id: str) -> str:
    space_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO spaces (id, name, tenant_id) VALUES (%s, 'Meetings', %s)",
            (space_id, tenant_id),
        )
    return space_id


def _set_home(connection, file_id: str, space_id: str | None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE files SET home_space_id = %s WHERE id = %s", (space_id, file_id)
        )


def _home(connection, file_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT home_space_id FROM files WHERE id = %s", (file_id,))
        row = cursor.fetchone()
    assert row is not None
    return None if row[0] is None else str(row[0])


def _home_schema(connection) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_name = 'files' AND column_name = 'home_space_id'"
        )
        column = cursor.fetchone()
        cursor.execute(
            "SELECT confdeltype, convalidated FROM pg_constraint"
            " WHERE conname = 'fk_files_home_space_id'"
        )
        key = cursor.fetchone()
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_files_home_space_id'"
        )
        index = cursor.fetchone()
    return {"column": column, "key": key, "index": index and index[0]}


def test_existing_files_get_an_empty_home(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file(connection, tenant_id=tenant_id, user_id=user_id)
    assert _home_schema(connection) == {"column": None, "key": None, "index": None}

    command.upgrade(config, REVISION)

    assert _home(connection, file_id) is None
    schema = _home_schema(connection)
    assert schema["column"] == ("YES",)
    # 'a' is NO ACTION: the key neither removes the file nor empties the home.
    assert schema["key"] == ("a", True)
    assert "WHERE (home_space_id IS NOT NULL)" in str(schema["index"])


def test_a_space_is_not_removed_from_under_a_file_and_the_home_is_kept(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)
    space_id = _space(connection, tenant_id=tenant_id)
    _set_home(connection, file_id, space_id)

    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM spaces WHERE id = %s", (space_id,))

    assert _home(connection, file_id) == space_id


def test_a_home_must_be_a_space(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)

    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _set_home(connection, file_id, str(uuid4()))


def test_an_organisation_is_removed_with_its_spaces_and_homed_files(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)
    space_id = _space(connection, tenant_id=tenant_id)
    _set_home(connection, file_id, space_id)

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        cursor.execute(
            "SELECT (SELECT count(*) FROM files WHERE id = %s),"
            " (SELECT count(*) FROM spaces WHERE id = %s)",
            (file_id, space_id),
        )
        assert cursor.fetchone() == (0, 0)


def test_downgrade_is_refused_while_a_file_has_a_home(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    file_id = _file(connection, tenant_id=tenant_id, user_id=user_id)
    command.upgrade(config, REVISION)
    space_id = _space(connection, tenant_id=tenant_id)
    _set_home(connection, file_id, space_id)

    with pytest.raises(RuntimeError, match="files have one"):
        command.downgrade(config, PRE_REVISION)

    assert _home(connection, file_id) == space_id


def test_downgrade_removes_the_home_and_upgrade_adds_it_again(migration_db) -> None:
    connection, config = migration_db
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    assert _home_schema(connection) == {"column": None, "key": None, "index": None}

    command.upgrade(config, REVISION)

    assert _home_schema(connection)["column"] == ("YES",)
