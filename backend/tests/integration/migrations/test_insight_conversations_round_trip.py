from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.migration_isolation

_REVISION = "202611111400"
_PREVIOUS_REVISION = "202611101200"
_TABLE = "insight_conversations"


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


def _schema(database_url: str) -> dict[str, object] | None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        if not inspector.has_table(_TABLE):
            return None
        return {
            "columns": {
                str(column["name"]): column["nullable"]
                for column in inspector.get_columns(_TABLE)
            },
            "foreign_keys": sorted(
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    fk["options"].get("ondelete"),
                )
                for fk in inspector.get_foreign_keys(_TABLE)
            ),
            "unique": sorted(
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(_TABLE)
            ),
            "checks": sorted(
                str(check["name"]) for check in inspector.get_check_constraints(_TABLE)
            ),
            "indexes": sorted(
                str(index["name"]) for index in inspector.get_indexes(_TABLE)
            ),
        }
    finally:
        engine.dispose()


_EXPECTED_SCHEMA = {
    "columns": {
        "id": False,
        "created_at": False,
        "updated_at": False,
        "tenant_id": False,
        "session_id": False,
        "assistant_id": True,
        "group_chat_id": True,
        "actor_user_id": True,
        "completion_model_id": True,
        "timezone": False,
    },
    "foreign_keys": [
        (("actor_user_id",), "users", "SET NULL"),
        (("assistant_id",), "assistants", "CASCADE"),
        (("completion_model_id",), "completion_models", "SET NULL"),
        (("group_chat_id",), "group_chats", "CASCADE"),
        (("session_id",), "sessions", "CASCADE"),
        (("tenant_id",), "tenants", "CASCADE"),
    ],
    "unique": [("uq_insight_conversations_session_id", ("session_id",))],
    "checks": ["ck_insight_conversations_target_xor"],
    # The unique constraint's own index serves the hidden-session lookup.
    "indexes": [
        "ix_insight_conversations_target_actor_created_at",
        "ix_insight_conversations_tenant_id",
        "uq_insight_conversations_session_id",
    ],
}


def test_insight_conversations_table_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="insight_conversations",
        password="insight_conversations_password",
        dbname="insight_conversations",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _schema(database_url) is None

        command.upgrade(config, _REVISION)
        assert _schema(database_url) == _EXPECTED_SCHEMA

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _schema(database_url) is None

        command.upgrade(config, _REVISION)
        assert _schema(database_url) == _EXPECTED_SCHEMA
