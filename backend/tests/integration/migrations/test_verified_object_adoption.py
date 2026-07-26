from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607251700"


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


def _current_revision(database_url: str) -> str | None:
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            row = cursor.fetchone()
            return None if row is None else str(row[0])
    finally:
        connection.close()


def test_verified_adoption_upgrade_downgrade_reupgrade_has_one_head() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="verified_adoption_migration",
        password="verified_adoption_migration_password",
        dbname="verified_adoption_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert len(heads) == 1
        head = heads[0]

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _current_revision(database_url) == _PREVIOUS_REVISION

        command.upgrade(config, "head")
        assert _current_revision(database_url) == head

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _current_revision(database_url) == _PREVIOUS_REVISION

        command.upgrade(config, "head")
        assert _current_revision(database_url) == head
