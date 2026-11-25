"""A deleted or migrated tenant model may have no provider."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISION = "202611251000"
_PREVIOUS_REVISION = "202611201305"


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
        username="hidden_models",
        password="hidden_models_password",
        dbname="hidden_models",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


_TABLES = (
    "completion_models",
    "transcription_models",
    "embedding_models",
    "image_models",
    "rerank_models",
)


def _rules(database_url: str) -> dict[str, str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) "
                    "FROM pg_constraint WHERE conname LIKE 'ck_%_models_tenant_provider'"
                )
            ).all()
        return {table: definition for table, definition in rows}
    finally:
        engine.dispose()


def test_tenant_provider_rule_round_trip(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database

    command.upgrade(config, _PREVIOUS_REVISION)
    before = _rules(database_url)
    assert set(before) == set(_TABLES)
    assert not any("deleted_at" in rule for rule in before.values())

    command.upgrade(config, _REVISION)
    after = _rules(database_url)
    assert all("deleted_at IS NOT NULL" in after[table] for table in _TABLES)
    assert {table for table in _TABLES if "migrated_to_model_id" in after[table]} == {
        "completion_models",
        "transcription_models",
    }

    command.downgrade(config, _PREVIOUS_REVISION)
    assert not any("deleted_at" in rule for rule in _rules(database_url).values())
