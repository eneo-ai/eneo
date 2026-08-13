from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

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
_PREVIOUS_REVISION = "202607231700"
_INDEX_REVISION = "202607241000"
_INDEXES = (
    "ix_questions_files_file_id",
    "ix_assistants_files_file_id",
    "ix_apps_files_file_id",
    "ix_app_runs_files_file_id",
)


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


def _index_state(database_url: str) -> dict[str, bool]:
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT indexrelid::regclass::text, indisvalid
            FROM pg_index
            WHERE indexrelid::regclass::text = ANY(%s)
            ORDER BY indexrelid::regclass::text
            """,
            (list(_INDEXES),),
        )
        return dict(cursor.fetchall())


def test_file_usage_indexes_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="file_usage_indexes",
        password="file_usage_indexes_password",
        dbname="file_usage_indexes",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _index_state(database_url) == {}

        command.upgrade(config, _INDEX_REVISION)
        assert _index_state(database_url) == dict.fromkeys(_INDEXES, True)

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _index_state(database_url) == {}

        command.upgrade(config, _INDEX_REVISION)
        assert _index_state(database_url) == dict.fromkeys(_INDEXES, True)
