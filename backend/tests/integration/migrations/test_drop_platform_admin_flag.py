"""Round-trip coverage for dropping users.is_platform_admin (202608101500).

The column was the interim authority for admin storage settings before
Permission.STORAGE existed. This migration removes it. The round trip matters
because the downgrade has to restore a NOT NULL column on a table that already
has rows, which only works if the restored column keeps its false default.
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_DROP_REVISION = "202608101300"
DROP_REVISION = "202608101500"


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
def drop_db(test_settings, monkeypatch):
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
    command.upgrade(config, PRE_DROP_REVISION)
    try:
        yield connection, config
    finally:
        connection.close()


def _column_exists(connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'is_platform_admin'"
        )
        return cursor.fetchone() is not None


def _user_count(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM users")
        return cursor.fetchone()[0]


def test_drop_removes_the_column_and_round_trips(drop_db) -> None:
    connection, config = drop_db

    assert _column_exists(connection)
    users_before = _user_count(connection)

    command.upgrade(config, DROP_REVISION)
    assert not _column_exists(connection)
    # Dropping an unused flag must not disturb the rows that carried it.
    assert _user_count(connection) == users_before

    command.downgrade(config, PRE_DROP_REVISION)
    assert _column_exists(connection)
    assert _user_count(connection) == users_before

    # Restored rows fall back to the safe default rather than NULL, so the
    # NOT NULL column is valid for pre-existing users.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM users WHERE is_platform_admin IS DISTINCT FROM false"
        )
        assert cursor.fetchone()[0] == 0
