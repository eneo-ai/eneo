from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISION = "202611021100"
_PREVIOUS_REVISION = "202610291900"


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


def _browser_sessions_schema(database_url: str) -> dict[str, object] | None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        if not inspector.has_table("browser_sessions"):
            return None
        return {
            "columns": {
                str(column["name"]): column["nullable"]
                for column in inspector.get_columns("browser_sessions")
            },
            "primary_key": inspector.get_pk_constraint("browser_sessions")[
                "constrained_columns"
            ],
            "foreign_keys": sorted(
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    fk["options"].get("ondelete"),
                )
                for fk in inspector.get_foreign_keys("browser_sessions")
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]))
                for index in inspector.get_indexes("browser_sessions")
            ),
        }
    finally:
        engine.dispose()


_EXPECTED_SCHEMA = {
    "columns": {
        "sid": False,
        "user_id": False,
        "tenant_id": False,
        "expires_at": False,
        "created_at": False,
    },
    "primary_key": ["sid"],
    "foreign_keys": [
        (("tenant_id",), "tenants", "CASCADE"),
        (("user_id",), "users", "CASCADE"),
    ],
    "indexes": [("ix_browser_sessions_user_id", ("user_id",))],
}


def test_browser_sessions_table_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="browser_sessions",
        password="browser_sessions_password",
        dbname="browser_sessions",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _browser_sessions_schema(database_url) is None

        command.upgrade(config, _REVISION)
        assert _browser_sessions_schema(database_url) == _EXPECTED_SCHEMA

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _browser_sessions_schema(database_url) is None

        command.upgrade(config, _REVISION)
        assert _browser_sessions_schema(database_url) == _EXPECTED_SCHEMA
