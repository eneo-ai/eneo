"""Lifecycle coverage for the candidate ownership-token allocator.

Slot 2's candidate revision is the token every delayed ownership check
compares against, and the temporary row is deleted whenever an attempt is
abandoned. The token therefore cannot come from a per-row counter, and the
allocator behind it must survive a downgrade: a stale administrator page or
a delayed request can outlive one, and a restarted allocator would let such
a token authorize an unrelated later attempt.
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

SLOT_REVISION = "202608061200"
PRE_SLOT_REVISION = "202607061000"
_SEQUENCE = "object_store_candidate_revision_seq"


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
def slot_db(test_settings, monkeypatch):
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
    command.upgrade(config, SLOT_REVISION)
    try:
        yield connection, config
    finally:
        connection.close()


def _sequence_exists(connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT to_regclass('{_SEQUENCE}') IS NOT NULL")
        return bool(cursor.fetchone()[0])


def _next_token(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT nextval('{_SEQUENCE}')")
        return int(cursor.fetchone()[0])


def test_candidate_tokens_are_never_reissued_across_a_schema_cycle(
    slot_db,
) -> None:
    connection, config = slot_db

    assert _sequence_exists(connection)
    issued = [_next_token(connection), _next_token(connection)]
    assert issued[1] > issued[0]

    # A downgrade removes slot 2 itself (it refuses while any temporary row
    # exists), but must leave the allocator behind: a client can still hold
    # one of the tokens above.
    command.downgrade(config, PRE_SLOT_REVISION)
    assert _sequence_exists(connection)

    command.upgrade(config, SLOT_REVISION)
    assert _sequence_exists(connection)

    # The decisive property: no token issued before the cycle can come back.
    after_cycle = _next_token(connection)
    assert after_cycle > max(issued)
