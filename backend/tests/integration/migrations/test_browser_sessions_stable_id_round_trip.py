"""Round trip for 202611091000: browser sessions get a stable id.

    pytest -m migration_isolation \
        tests/integration/migrations/test_browser_sessions_stable_id_round_trip.py
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611081500"
REVISION = "202611091000"


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


def _keys(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        return {
            "id": "id"
            in {column["name"] for column in inspector.get_columns("browser_sessions")},
            "primary_key": inspector.get_pk_constraint("browser_sessions")[
                "constrained_columns"
            ],
            "unique": sorted(
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("browser_sessions")
            ),
        }
    finally:
        engine.dispose()


def _seed_sessions(conn) -> tuple[UUID, UUID, list[str]]:
    """A user with two live sessions and one that has expired."""
    tenant_id, user_id = uuid4(), uuid4()
    sids = [f"{index}" * 43 for index in range(3)]
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state)"
            " VALUES (%s, %s, 1000000, 'active')",
            (str(tenant_id), f"stable-id-{tenant_id.hex[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state)"
            " VALUES (%s, %s, %s, 0, 'active')",
            (str(user_id), str(tenant_id), f"{user_id.hex}@example.test"),
        )
        for sid, expires_at in zip(
            sids,
            (
                now + timedelta(hours=1),
                now + timedelta(hours=2),
                now - timedelta(minutes=1),
            ),
        ):
            cursor.execute(
                "INSERT INTO browser_sessions (sid, user_id, tenant_id, expires_at)"
                " VALUES (%s, %s, %s, %s)",
                (sid, str(user_id), str(tenant_id), expires_at),
            )
    return tenant_id, user_id, sids


def _admitted(conn, tenant_id: UUID, user_id: UUID) -> set[str]:
    """The sessions a token carrying only their sid is admitted under."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT sid FROM browser_sessions WHERE user_id = %s AND tenant_id = %s"
            " AND expires_at > now()",
            (str(user_id), str(tenant_id)),
        )
        return {sid for (sid,) in cursor.fetchall()}


def _ids(conn) -> dict[str, UUID]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT sid, id FROM browser_sessions")
        return {sid: UUID(str(id_)) for sid, id_ in cursor.fetchall()}


def test_live_sessions_get_a_stable_id_and_survive_the_round_trip() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="browser_sessions_id",
        password="browser_sessions_id_password",
        dbname="browser_sessions_id",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, PRE_REVISION)
        conn = psycopg2.connect(database_url.replace("+psycopg2", ""))
        conn.autocommit = True
        try:
            tenant_id, user_id, sids = _seed_sessions(conn)
            live = set(sids[:2])
            assert _admitted(conn, tenant_id, user_id) == live

            command.upgrade(config, REVISION)
            assert _keys(database_url) == {
                "id": True,
                "primary_key": ["id"],
                "unique": [("sid",)],
            }
            ids = _ids(conn)
            # Each existing row got its own id; the sessions are the same ones.
            assert ids.keys() == set(sids)
            assert len(set(ids.values())) == 3
            assert _admitted(conn, tenant_id, user_id) == live
            # A new row gets an id from the database; a sid stays unique.
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO browser_sessions (sid, user_id, tenant_id, expires_at)"
                    " VALUES (%s, %s, %s, now() + interval '1 hour') RETURNING id",
                    ("n" * 43, str(user_id), str(tenant_id)),
                )
                assert cursor.fetchone()[0] is not None
            with pytest.raises(psycopg2.errors.UniqueViolation):
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO browser_sessions"
                        " (sid, user_id, tenant_id, expires_at)"
                        " VALUES (%s, %s, %s, now())",
                        (sids[0], str(user_id), str(tenant_id)),
                    )
            live.add("n" * 43)

            command.downgrade(config, PRE_REVISION)
            assert _keys(database_url) == {
                "id": False,
                "primary_key": ["sid"],
                "unique": [],
            }
            assert _admitted(conn, tenant_id, user_id) == live

            command.upgrade(config, REVISION)
            assert _keys(database_url)["primary_key"] == ["id"]
            assert _admitted(conn, tenant_id, user_id) == live
        finally:
            conn.close()
