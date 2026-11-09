"""The times a conversation's name and feedback text were written (202611091200).

Existing conversations get their creation time: never later than their first
question, so no name or feedback text written before the upgrade is kept
longer than its conversation's period allows. New conversations get the time
of their creation from the database.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611091110"
REVISION = "202611091200"


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
        username="session_text_times",
        password="session_text_times_password",
        dbname="session_text_times",
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


def _seed(connection, *, created_at: datetime, asked_at: datetime) -> str:
    tenant_id, user_id, session_id = (str(uuid4()) for _ in range(3))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state) "
            "VALUES (%s, %s, 1000000, 'active')",
            (tenant_id, f"session-text-times-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
            "VALUES (%s, %s, %s, 0, 'active')",
            (user_id, tenant_id, f"{user_id}@example.test"),
        )
        # Renamed and given feedback long after it began.
        cursor.execute(
            "INSERT INTO sessions (id, user_id, name, feedback_value, feedback_text,"
            " created_at, updated_at) VALUES (%s, %s, 'Renamed', 1, 'Feedback', %s, %s)",
            (session_id, user_id, created_at, created_at + timedelta(days=30)),
        )
        cursor.execute(
            "INSERT INTO questions (id, question, answer, num_tokens_question,"
            " num_tokens_answer, tenant_id, session_id, created_at, updated_at)"
            " VALUES (%s, 'Question', 'Answer', 1, 1, %s, %s, %s, %s)",
            (str(uuid4()), tenant_id, session_id, asked_at, asked_at),
        )
    return session_id


def _times(
    connection, session_id: str
) -> tuple[datetime, datetime, datetime, datetime]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT s.name_set_at, s.feedback_set_at, s.created_at,"
            " (SELECT min(q.created_at) FROM questions q WHERE q.session_id = s.id)"
            " FROM sessions s WHERE s.id = %s",
            (session_id,),
        )
        return cursor.fetchone()


def test_existing_conversations_get_their_creation_time(migration_db) -> None:
    connection, config = migration_db
    began = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
    session_id = _seed(
        connection, created_at=began, asked_at=began + timedelta(seconds=5)
    )

    command.upgrade(config, REVISION)

    name_set_at, feedback_set_at, created_at, first_question = _times(
        connection, session_id
    )
    assert name_set_at == feedback_set_at == created_at == began
    assert name_set_at <= first_question


def test_new_conversations_get_the_time_they_were_written(migration_db) -> None:
    connection, config = migration_db
    command.upgrade(config, REVISION)
    session_id = _seed(
        connection,
        created_at=datetime.now(timezone.utc),
        asked_at=datetime.now(timezone.utc),
    )

    name_set_at, feedback_set_at, _, _ = _times(connection, session_id)
    assert name_set_at is not None and feedback_set_at is not None

    command.downgrade(config, PRE_REVISION)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'sessions'"
            " AND column_name IN ('name_set_at', 'feedback_set_at')"
        )
        assert cursor.fetchall() == []
