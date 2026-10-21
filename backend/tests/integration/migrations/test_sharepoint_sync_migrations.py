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
_BEFORE = "202610191030"
_LIFECYCLE_REVISION = "202610191400"
_INDEX_REVISION = "202610191500"
_INDEX = "ix_info_blobs_integration_knowledge_sharepoint_item"


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


def _query(database_url: str, sql: str, *params: object) -> list[tuple[object, ...]]:
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


def _has_lifecycle_column(database_url: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns WHERE table_name = "
            "'sharepoint_subscriptions' AND column_name = 'lifecycle_notification_url'",
        )
    )


def _index(database_url: str) -> list[tuple[object, ...]]:
    return _query(
        database_url,
        "SELECT indisvalid, pg_get_indexdef(indexrelid) FROM pg_index "
        "WHERE indexrelid::regclass::text = %s",
        _INDEX,
    )


def _generic_plan_uses_the_index(database_url: str) -> bool:
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET plan_cache_mode = force_generic_plan")
        cursor.execute("SET enable_seqscan = off")
        cursor.execute(
            "PREPARE lookup(text, uuid) AS SELECT id FROM info_blobs "
            "WHERE sharepoint_item_id = $1 AND integration_knowledge_id = $2"
        )
        cursor.execute(
            "EXPLAIN EXECUTE lookup('item', '00000000-0000-0000-0000-000000000000')"
        )
        return any(_INDEX in str(row[0]) for row in cursor.fetchall())


def test_sharepoint_sync_migrations_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="sharepoint_sync",
        password="sharepoint_sync_password",
        dbname="sharepoint_sync",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _BEFORE)
        assert not _has_lifecycle_column(database_url)
        assert _index(database_url) == []

        command.upgrade(config, _INDEX_REVISION)
        assert _has_lifecycle_column(database_url)
        [(valid, definition)] = _index(database_url)
        assert valid is True
        assert "(integration_knowledge_id, sharepoint_item_id)" in str(definition)
        assert "WHERE (sharepoint_item_id IS NOT NULL)" in str(definition)
        assert _generic_plan_uses_the_index(database_url)

        command.downgrade(config, _LIFECYCLE_REVISION)
        assert _index(database_url) == []
        assert _has_lifecycle_column(database_url)

        command.downgrade(config, _BEFORE)
        assert not _has_lifecycle_column(database_url)

        command.upgrade(config, _INDEX_REVISION)
        assert _has_lifecycle_column(database_url)
        assert [valid for valid, _ in _index(database_url)] == [True]
