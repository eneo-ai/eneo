from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    InfoBlobContentReferences,
    ObjectContentAuditEvents,
    ObjectContentHolds,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContentReconciliationState,
    ObjectContents,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607071200"
_FOUNDATION_REVISION = "202607151200"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    """Keep this migration packet independent of the shared PG16 fixture."""
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
        image=_POSTGRES_13_IMAGE,
        username="object_content_migration",
        password="object_content_migration_password",
        dbname="object_content_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _current_revision(database_url: str) -> str | None:
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            row = cursor.fetchone()
            return None if row is None else str(row[0])
    finally:
        connection.close()


def _table_exists(database_url: str, table_name: str) -> bool:
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", (table_name,))
            return cursor.fetchone()[0] is not None
    finally:
        connection.close()


def test_fresh_upgrade_downgrade_reupgrade_and_orm_parity(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database

    command.upgrade(config, "head")
    assert _current_revision(database_url) == _FOUNDATION_REVISION

    models = (
        ObjectContents,
        ObjectContentHolds,
        FileContentReferences,
        InfoBlobContentReferences,
        IconContentReferences,
        ObjectContentAuditEvents,
        ObjectContentOrphanCandidates,
        ObjectContentMultipartCandidates,
        ObjectContentReconciliationState,
    )
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        for model in models:
            table_name = model.__tablename__
            database_columns = {
                str(column["name"]) for column in inspector.get_columns(table_name)
            }
            orm_columns = {column.name for column in model.__table__.columns}
            assert database_columns == orm_columns, table_name
    finally:
        engine.dispose()

    command.downgrade(config, _PREVIOUS_REVISION)
    assert _current_revision(database_url) == _PREVIOUS_REVISION
    assert not _table_exists(database_url, "object_contents")
    assert not _table_exists(database_url, "object_content_reconciliation_state")

    command.upgrade(config, "head")
    assert _current_revision(database_url) == _FOUNDATION_REVISION
    assert _table_exists(database_url, "object_contents")
