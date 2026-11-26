from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISION = "202611021100"
_PREVIOUS_REVISION = "202610291900"
_MFA_REVISION = "202611271000"
_BEFORE_MFA_REVISION = "202611201305"


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


def _mfa_columns(database_url: str) -> dict[str, tuple[bool, str | None]]:
    """Each MFA column that exists: whether it may be empty, and its default."""
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        return {
            f"{table}.{column['name']}": (column["nullable"], column["default"])
            for table in ("browser_sessions", "spaces")
            for column in inspector.get_columns(table)
            if column["name"] in ("mfa", "mfa_required")
        }
    finally:
        engine.dispose()


def test_mfa_on_the_session_and_the_space_requirement_round_trip() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="session_mfa",
        password="session_mfa_password",
        dbname="session_mfa",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _BEFORE_MFA_REVISION)
        assert _mfa_columns(database_url) == {}
        tenant_id, user_id, space_id = str(uuid4()), str(uuid4()), str(uuid4())
        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, quota_limit, state)"
                        " VALUES (:tenant, 'session-mfa', 1000000, 'active')"
                    ),
                    {"tenant": tenant_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO users (id, tenant_id, email, used_tokens, state)"
                        " VALUES (:user, :tenant, 'person@example.test', 0, 'active')"
                    ),
                    {"user": user_id, "tenant": tenant_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO browser_sessions"
                        " (sid, user_id, tenant_id, expires_at)"
                        " VALUES ('sid-from-before', :user, :tenant, now())"
                    ),
                    {"user": user_id, "tenant": tenant_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO spaces (id, name, tenant_id)"
                        " VALUES (:space, 'Meetings', :tenant)"
                    ),
                    {"space": space_id, "tenant": tenant_id},
                )

            command.upgrade(config, _MFA_REVISION)

            assert _mfa_columns(database_url) == {
                "browser_sessions.mfa": (False, "false"),
                "spaces.mfa_required": (False, "false"),
            }
            # What existed before was judged under no rule and required nothing.
            with engine.begin() as connection:
                assert connection.execute(
                    text("SELECT mfa FROM browser_sessions")
                ).scalars().all() == [False]
                assert connection.execute(
                    text("SELECT mfa_required FROM spaces")
                ).scalars().all() == [False]
                connection.execute(text("UPDATE spaces SET mfa_required = true"))

            # The earlier release would open the space to sessions without MFA.
            with pytest.raises(RuntimeError, match="1 spaces require MFA"):
                command.downgrade(config, _BEFORE_MFA_REVISION)
            assert len(_mfa_columns(database_url)) == 2

            with engine.begin() as connection:
                connection.execute(text("UPDATE spaces SET mfa_required = false"))
                connection.execute(text("UPDATE browser_sessions SET mfa = true"))
            command.downgrade(config, _BEFORE_MFA_REVISION)
            assert _mfa_columns(database_url) == {}

            command.upgrade(config, _MFA_REVISION)
            with engine.begin() as connection:
                assert connection.execute(
                    text("SELECT mfa FROM browser_sessions")
                ).scalars().all() == [False]
        finally:
            engine.dispose()
