from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_BEFORE = "202610191500"
_REVISION = "202610191600"


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


def _column(database_url: str) -> list[tuple[object, ...]]:
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = "
            "'integration_knowledge' AND column_name = 'sync_failed_items'"
        )
        return cursor.fetchall()


def test_sync_failed_items_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="sharepoint_ledger",
        password="sharepoint_ledger_password",
        dbname="sharepoint_ledger",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _BEFORE)
        assert _column(database_url) == []

        command.upgrade(config, _REVISION)
        assert _column(database_url) == [("jsonb", "YES", None)]

        command.downgrade(config, _BEFORE)
        assert _column(database_url) == []

        command.upgrade(config, _REVISION)
        assert _column(database_url) == [("jsonb", "YES", None)]
