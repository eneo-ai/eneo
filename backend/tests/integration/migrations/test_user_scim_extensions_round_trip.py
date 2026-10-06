from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISION = "202609281000"
_PREVIOUS_REVISION = "202609221000"


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
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="scim_extensions",
        password="scim_extensions_password",
        dbname="scim_extensions",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _user_columns(database_url: str) -> dict[str, dict[str, object]]:
    engine = create_engine(database_url)
    try:
        return {
            str(column["name"]): dict(column)
            for column in inspect(engine).get_columns("users")
        }
    finally:
        engine.dispose()


def test_scim_extensions_column_round_trip(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database

    command.upgrade(config, _PREVIOUS_REVISION)
    assert "scim_extensions" not in _user_columns(database_url)

    command.upgrade(config, _REVISION)
    column = _user_columns(database_url)["scim_extensions"]
    assert column["nullable"] is True
    assert str(column["type"]) == "JSONB"

    command.downgrade(config, _PREVIOUS_REVISION)
    assert "scim_extensions" not in _user_columns(database_url)
