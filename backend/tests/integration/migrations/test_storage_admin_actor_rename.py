"""Round-trip coverage for the storage-admin actor rename (202608101300).

The rename converts persisted 'platform_admin' actors to 'storage_admin' on
both storage-owned tables and tightens their check constraints. The generic
head upgrade in other suites never exercises the conversion because their
rows use the 'migration' actor. Both tables are seeded and asserted here.
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_RENAME_REVISION = "202608061600"
RENAME_REVISION = "202608101300"

_TABLES = ("object_content_deployment_policy", "object_store_connections")


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def rename_db(test_settings, monkeypatch):
    for variable in (
        "UPLOAD_FILE_TO_SESSION_MAX_SIZE",
        "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE",
        "UPLOAD_MAX_FILE_SIZE",
        "TRANSCRIPTION_MAX_FILE_SIZE",
    ):
        monkeypatch.delenv(variable, raising=False)
    config = _alembic_cfg(test_settings.sync_database_url)
    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    connection.autocommit = True
    command.upgrade(config, PRE_RENAME_REVISION)
    with connection.cursor() as cursor:
        # Historical rows written when this boundary still recorded the
        # overstated label — one per affected table.
        cursor.execute(
            "UPDATE object_content_deployment_policy "
            "SET updated_by_actor = 'platform_admin' WHERE id = 1"
        )
        cursor.execute(
            """
            INSERT INTO object_store_connections (
                id, revision, role, endpoint_url, region, bucket,
                access_key_id_encrypted, secret_access_key_encrypted,
                deployment_id, addressing_style, updated_by_actor
            )
            VALUES (
                1, 1, 'active', 'https://objects.example.test', 'local',
                'eneo-content', 'enc-key-id', 'enc-secret',
                %s, 'path', 'platform_admin'
            )
            ON CONFLICT (id) DO UPDATE
                SET updated_by_actor = 'platform_admin', revision = 1
            """,
            (str(uuid4()),),
        )
    try:
        yield connection, config
    finally:
        connection.close()


def _actor(connection, table: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT updated_by_actor FROM {table} WHERE id = 1")
        return cursor.fetchone()[0]


def _actor_accepted(connection, table: str, value: str) -> bool:
    with connection.cursor() as cursor:
        try:
            cursor.execute(
                f"UPDATE {table} SET updated_by_actor = %s WHERE id = 1",
                (value,),
            )
        except psycopg2.errors.CheckViolation:
            return False
        return True


def test_rename_converts_history_and_round_trips(rename_db) -> None:
    connection, config = rename_db

    for table in _TABLES:
        assert _actor(connection, table) == "platform_admin"

    command.upgrade(config, RENAME_REVISION)
    for table in _TABLES:
        assert _actor(connection, table) == "storage_admin"
        # The tightened constraint rejects the retired vocabulary and
        # accepts the new one.
        assert not _actor_accepted(connection, table, "platform_admin")
        assert _actor_accepted(connection, table, "storage_admin")

    command.downgrade(config, PRE_RENAME_REVISION)
    for table in _TABLES:
        assert _actor(connection, table) == "platform_admin"
        assert not _actor_accepted(connection, table, "storage_admin")
        assert _actor_accepted(connection, table, "platform_admin")
