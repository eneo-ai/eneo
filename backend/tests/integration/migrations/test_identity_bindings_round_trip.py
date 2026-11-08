"""Round trip for 202611091010: accounts bound to provider identities.

    pytest -m migration_isolation \
        tests/integration/migrations/test_identity_bindings_round_trip.py
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611091000"
REVISION = "202611091010"


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


def _schema(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        schema: dict[str, object] = {
            "tables": tables & {"identity_bindings", "identity_migration_windows"},
            "rebinding_column": "identity_rebinding_until"
            in {column["name"] for column in inspector.get_columns("users")},
        }
        if "identity_bindings" in tables:
            schema["unique"] = sorted(
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("identity_bindings")
            )
        return schema
    finally:
        engine.dispose()


def test_bindings_and_rebinding_round_trip_keeping_accounts() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="identity_bindings",
        password="identity_bindings_password",
        dbname="identity_bindings",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, PRE_REVISION)
        conn = psycopg2.connect(database_url.replace("+psycopg2", ""))
        conn.autocommit = True
        try:
            tenant_id, user_id = uuid4(), uuid4()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tenants (id, name, quota_limit, state)"
                    " VALUES (%s, %s, 1000000, 'active')",
                    (str(tenant_id), f"bindings-{tenant_id.hex[:8]}"),
                )
                cursor.execute(
                    "INSERT INTO users (id, tenant_id, email, used_tokens, state)"
                    " VALUES (%s, %s, %s, 0, 'active')",
                    (str(user_id), str(tenant_id), f"{user_id.hex}@example.test"),
                )

            command.upgrade(config, REVISION)
            assert _schema(database_url) == {
                "tables": {"identity_bindings", "identity_migration_windows"},
                "rebinding_column": True,
                "unique": [
                    ("tenant_id", "issuer", "subject_claim", "subject", "audience"),
                    ("user_id", "issuer", "audience"),
                ],
            }
            # Existing accounts start unbound, with no allowance open.
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT identity_rebinding_until FROM users WHERE id = %s",
                    (str(user_id),),
                )
                assert cursor.fetchone() == (None,)
                cursor.execute(
                    "INSERT INTO identity_bindings"
                    " (tenant_id, user_id, issuer, audience, subject_claim, subject)"
                    " VALUES (%s, %s, 'https://idp', 'client', 'sub', 'subject')",
                    (str(tenant_id), str(user_id)),
                )
                # A window may lead to its own pair (a new subject claim).
                cursor.execute(
                    "INSERT INTO identity_migration_windows (tenant_id,"
                    " from_issuer, from_audience, to_issuer, to_audience,"
                    " closes_at) VALUES (%s, 'i', 'a', 'i', 'a', now())",
                    (str(tenant_id),),
                )

            command.downgrade(config, PRE_REVISION)
            assert _schema(database_url) == {"tables": set(), "rebinding_column": False}
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM users WHERE id = %s", (str(user_id),)
                )
                assert cursor.fetchone() == (1,)

            command.upgrade(config, REVISION)
            assert _schema(database_url)["rebinding_column"] is True
        finally:
            conn.close()
