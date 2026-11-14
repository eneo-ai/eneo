"""Round trip for 202611141200: assistants.external_clients_enabled.

    pytest -m migration_isolation \
        tests/integration/migrations/test_assistant_external_clients_round_trip.py
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611091200"
REVISION = "202611141200"
COLUMN = "external_clients_enabled"


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


@pytest.fixture(scope="module")
def migrated_db():
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="external_clients",
        password="external_clients_password",
        dbname="external_clients",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, REVISION)
        conn = psycopg2.connect(database_url.replace("+psycopg2", ""))
        conn.autocommit = True
        try:
            yield conn, config
        finally:
            conn.close()


def _column(conn) -> tuple[str, str, str | None] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'assistants' AND column_name = %s",
            (COLUMN,),
        )
        return cursor.fetchone()


def test_upgrade_adds_a_required_flag_that_is_off(migrated_db):
    conn, _config = migrated_db

    assert _column(conn) == ("boolean", "NO", "false")


def test_downgrade_drops_the_column_and_upgrade_restores_it(migrated_db):
    conn, config = migrated_db

    command.downgrade(config, PRE_REVISION)
    assert _column(conn) is None

    command.upgrade(config, REVISION)
    assert _column(conn) == ("boolean", "NO", "false")
