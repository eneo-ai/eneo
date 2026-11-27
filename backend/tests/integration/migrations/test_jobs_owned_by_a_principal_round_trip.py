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

REVISION = "202611251100"
PRE_REVISION = "202611251000"


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
        username="job_owner",
        password="job_owner_password",
        dbname="job_owner",
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
            (tenant_id, f"job-owner-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
    return tenant_id, user_id


def _service_key(connection, *, tenant_id: str) -> tuple[str, str]:
    """A service principal and a key of it."""
    principal_id, key_id = str(uuid4()), str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO service_principals (id, tenant_id, display_name, scope_type) "
            "VALUES (%s, %s, 'Invoice reader', 'tenant')",
            (principal_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO api_keys_v2 (id, tenant_id, ownership, service_principal_id,"
            " scope_type, permission, key_type, key_hash, hash_version, key_prefix,"
            " key_suffix, name, state) VALUES (%s, %s, 'service', %s, 'tenant',"
            " 'read', 'sk_', %s, 'hmac_sha256', 'sk_', 'abcd', 'Invoice reader',"
            " 'active')",
            (key_id, tenant_id, principal_id, f"hash-{key_id}"),
        )
    return principal_id, key_id


def _job(connection, **owner: str | None) -> str:
    job_id = str(uuid4())
    columns = {"id": job_id, "task": "run_app", "status": "queued", **owner}
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO jobs ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            list(columns.values()),
        )
    return job_id


def _owner(connection, job_id: str) -> tuple[str | None, str | None, str | None]:
    """(person, service principal, key) of a job."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id, service_principal_id, api_key_id FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cursor.fetchone()
    return tuple(None if value is None else str(value) for value in row)


def test_existing_jobs_keep_their_person(migration_db) -> None:
    connection, config = migration_db
    _, user_id = _tenant_with_user(connection)
    job_id = _job(connection, user_id=user_id)

    command.upgrade(config, REVISION)

    assert _owner(connection, job_id) == (user_id, None, None)


def test_a_job_can_belong_to_a_service_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id, key_id = _service_key(connection, tenant_id=tenant_id)

    job_id = _job(connection, service_principal_id=principal_id, api_key_id=key_id)

    assert _owner(connection, job_id) == (None, principal_id, key_id)


def test_a_job_has_at_most_one_owner_and_a_key_only_with_its_principal(
    migration_db,
) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id, key_id = _service_key(connection, tenant_id=tenant_id)

    with pytest.raises(psycopg2.errors.CheckViolation):
        _job(connection, user_id=user_id, service_principal_id=principal_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _job(connection, api_key_id=key_id)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _job(connection, user_id=user_id, api_key_id=key_id)

    without_an_owner = _job(connection)
    assert _owner(connection, without_an_owner) == (None, None, None)


def test_removing_a_key_keeps_its_jobs_with_the_principal(migration_db) -> None:
    connection, config = migration_db
    tenant_id, _ = _tenant_with_user(connection)
    command.upgrade(config, REVISION)
    principal_id, key_id = _service_key(connection, tenant_id=tenant_id)
    job_id = _job(connection, service_principal_id=principal_id, api_key_id=key_id)

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM api_keys_v2 WHERE id = %s", (key_id,))

    assert _owner(connection, job_id) == (None, principal_id, None)
    with (
        pytest.raises(psycopg2.errors.ForeignKeyViolation),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))


def test_downgrade_is_refused_while_a_job_belongs_to_no_person(migration_db) -> None:
    connection, config = migration_db
    tenant_id, user_id = _tenant_with_user(connection)
    persons = _job(connection, user_id=user_id)
    command.upgrade(config, REVISION)
    principal_id, key_id = _service_key(connection, tenant_id=tenant_id)
    services = _job(connection, service_principal_id=principal_id, api_key_id=key_id)

    with pytest.raises(RuntimeError, match="belong to no person"):
        command.downgrade(config, PRE_REVISION)

    assert _owner(connection, services) == (None, principal_id, key_id)
    assert _owner(connection, persons) == (user_id, None, None)


def test_downgrade_requires_a_person_again_and_upgrade_frees_it(migration_db) -> None:
    connection, config = migration_db
    _, user_id = _tenant_with_user(connection)
    job_id = _job(connection, user_id=user_id)
    command.upgrade(config, REVISION)

    command.downgrade(config, PRE_REVISION)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'jobs' AND column_name IN"
            " ('user_id', 'service_principal_id', 'api_key_id')"
        )
        assert dict(cursor.fetchall()) == {"user_id": "NO"}
        cursor.execute("SELECT user_id FROM jobs WHERE id = %s", (job_id,))
        assert str(cursor.fetchone()[0]) == user_id

    command.upgrade(config, REVISION)

    assert _owner(connection, job_id) == (user_id, None, None)
