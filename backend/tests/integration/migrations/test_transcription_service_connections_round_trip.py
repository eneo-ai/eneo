from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.tables.transcription_services_table import (
    SpacesTranscriptionServiceConnections,
    TranscriptionServiceConnections,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISION = "202610090800"
_OPERATIONS_REVISION = "202610082100"
_PREVIOUS_REVISION = "202610081100"
_TABLES = (
    "transcription_service_connections",
    "spaces_transcription_service_connections",
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


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="transcription_services",
        password="transcription_services_password",
        dbname="transcription_services",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _checks(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return {
            check["name"]
            for check in inspect(engine).get_check_constraints(
                "transcription_service_connections"
            )
        }
    finally:
        engine.dispose()


def _tables(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names()) & set(_TABLES)
    finally:
        engine.dispose()


def test_the_tables_round_trip_and_match_the_models(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database

    command.upgrade(config, _PREVIOUS_REVISION)
    assert _tables(database_url) == set()

    command.upgrade(config, _OPERATIONS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        tenant_id = connection.execute(
            text(
                "INSERT INTO tenants (name, quota_limit, state) "
                "VALUES ('migration tenant', 1, 'active') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO transcription_service_connections "
                "(tenant_id, name, endpoint_url, api_key_encrypted, operations) "
                "VALUES (:tenant, 'vemsa', 'https://x', 'enc', '{transcribe}')"
            ),
            {"tenant": tenant_id},
        )
    engine.dispose()

    command.upgrade(config, _REVISION)
    assert _tables(database_url) == set(_TABLES)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        for model in (
            TranscriptionServiceConnections,
            SpacesTranscriptionServiceConnections,
        ):
            table = model.__table__
            columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns(table.name)
            }
            assert columns == {column.name: column.nullable for column in table.columns}
            assert {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    fk["options"].get("ondelete"),
                )
                for fk in inspector.get_foreign_keys(table.name)
            } == {
                (
                    tuple(fk.parent.name for fk in constraint.elements),
                    constraint.referred_table.name,
                    constraint.ondelete,
                )
                for constraint in table.foreign_key_constraints
            }
        assert _checks(database_url) == set()
        assert {
            unique["name"]
            for unique in inspector.get_unique_constraints(
                "transcription_service_connections"
            )
        } == {"uq_transcription_service_connections_name"}
        assert {
            index["name"]
            for index in inspector.get_indexes(
                "spaces_transcription_service_connections"
            )
        } == {"ix_spaces_transcription_service_connections_connection_id"}
    finally:
        engine.dispose()

    # Downgrading restores the column; a kept connection is a speaker service.
    command.downgrade(config, _OPERATIONS_REVISION)
    assert _checks(database_url) == {"ck_transcription_service_connections_operations"}
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT operations FROM transcription_service_connections")
            ).scalars().all() == [["diarize"]]
    finally:
        engine.dispose()

    command.downgrade(config, _PREVIOUS_REVISION)
    assert _tables(database_url) == set()
    command.upgrade(config, _REVISION)
