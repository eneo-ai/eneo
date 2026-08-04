"""The chunk-config migration's index must survive upgrade, downgrade and re-upgrade.

The index is created with ``CREATE INDEX CONCURRENTLY`` inside an autocommit block, so
two things are worth proving rather than assuming: that it ends up valid rather than
left behind in the invalid state a failed concurrent build produces, and that the
``IF NOT EXISTS`` guard does not skip a rebuild after a downgrade.
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

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607311000"
_CHUNK_REVISION = "202607311121"
_INDEX = "ix_info_blobs_integration_knowledge_chunking"


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
            WHERE indexrelid::regclass::text = %s
            """,
            (_INDEX,),
        )
        return dict(cursor.fetchall())


def _chunk_columns(database_url: str) -> set[tuple[str, str]]:
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE column_name IN ('chunk_size', 'chunk_overlap')
              AND table_name IN ('groups', 'websites',
                                 'integration_knowledge', 'info_blobs')
            """
        )
        return {(row[0], row[1]) for row in cursor.fetchall()}


def test_chunk_config_index_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="chunk_config_index",
        password="chunk_config_index_password",
        dbname="chunk_config_index",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _index_state(database_url) == {}
        assert _chunk_columns(database_url) == set()

        command.upgrade(config, _CHUNK_REVISION)
        # Valid, not the invalid leftover a failed concurrent build would produce.
        assert _index_state(database_url) == {_INDEX: True}
        assert _chunk_columns(database_url) == {
            (table, column)
            for table in ("groups", "websites", "integration_knowledge", "info_blobs")
            for column in ("chunk_size", "chunk_overlap")
        }

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _index_state(database_url) == {}
        assert _chunk_columns(database_url) == set()

        # IF NOT EXISTS must not turn the rebuild into a silent no-op.
        command.upgrade(config, _CHUNK_REVISION)
        assert _index_state(database_url) == {_INDEX: True}
