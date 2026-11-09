"""Logs that no question refers to are removed on upgrade, and the index of
logged turns is valid after an upgrade that follows a failed build.

Before removal took a question's log with it, deleting a question left its log
behind with the whole request body, and an answer completed after its
question was gone stored a log nothing refers to. Nothing can read or remove
such a log later, so the upgrade removes it once.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202611081500"


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


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _connect(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _insert_logs(database_url: str) -> tuple[str, str]:
    """An orphan log and a log its question still refers to."""
    tenant_id, user_id, session_id = str(uuid4()), str(uuid4()), str(uuid4())
    orphan_id, referenced_id = str(uuid4()), str(uuid4())
    connection = _connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, quota_limit, state) "
                "VALUES (%s, %s, 1000000, 'active')",
                (tenant_id, f"orphan-logs-{uuid4().hex[:8]}"),
            )
            cursor.execute(
                "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
                "VALUES (%s, %s, %s, %s, 0, 'active')",
                (
                    user_id,
                    tenant_id,
                    f"orphan-logs-{uuid4().hex[:8]}",
                    f"orphan-logs-{uuid4().hex[:12]}@example.test",
                ),
            )
            cursor.execute(
                "INSERT INTO logging (id, model_kwargs, json_body) VALUES "
                "(%s, '{}', '\"[removed question]\"'), "
                "(%s, '{}', '\"[kept question]\"')",
                (orphan_id, referenced_id),
            )
            cursor.execute(
                "INSERT INTO sessions (id, user_id, name) VALUES (%s, %s, 'kept')",
                (session_id, user_id),
            )
            cursor.execute(
                "INSERT INTO questions (id, question, answer, num_tokens_question, "
                "num_tokens_answer, tenant_id, session_id, logging_details_id) "
                "VALUES (%s, 'kept question', 'kept answer', 1, 1, %s, %s, %s)",
                (str(uuid4()), tenant_id, session_id, referenced_id),
            )
    finally:
        connection.close()
    return orphan_id, referenced_id


def _log_ids(database_url: str) -> set[str]:
    connection = _connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id::text FROM logging")
            return {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()


def test_logs_no_question_refers_to_are_removed_on_upgrade() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="orphan_logs_migration",
        password="orphan_logs_migration_password",
        dbname="orphan_logs_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        orphan_id, referenced_id = _insert_logs(database_url)
        assert _log_ids(database_url) == {orphan_id, referenced_id}

        command.upgrade(config, "head")
        assert _log_ids(database_url) == {referenced_id}

        command.downgrade(config, _PREVIOUS_REVISION)
        command.upgrade(config, "head")
        assert _log_ids(database_url) == {referenced_id}


def _logged_turns_index_valid(database_url: str) -> bool | None:
    connection = _connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indisvalid FROM pg_index "
                "WHERE indexrelid = to_regclass('ix_questions_logged_turns')"
            )
            row = cursor.fetchone()
            return None if row is None else row[0]
    finally:
        connection.close()


def test_an_index_a_failed_build_left_invalid_is_rebuilt_on_upgrade() -> None:
    """A concurrent build that fails leaves the index invalid, and PostgreSQL
    does not use it. Mutant: the rerun keeps it because it exists."""
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="logged_turns_migration",
        password="logged_turns_migration_password",
        dbname="logged_turns_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        connection = _connect(database_url)
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    "CREATE INDEX ix_questions_logged_turns ON questions (session_id)"
                )
                cursor.execute(
                    "UPDATE pg_index SET indisvalid = false "
                    "WHERE indexrelid = 'ix_questions_logged_turns'::regclass"
                )
        finally:
            connection.close()
        assert _logged_turns_index_valid(database_url) is False

        command.upgrade(config, "head")

        assert _logged_turns_index_valid(database_url) is True
