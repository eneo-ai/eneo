from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

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
_REVISION = "202611031000"
_PREVIOUS_REVISION = "202611030830"
_STATISTICS = {
    "audit_logs_lower_description_stat": (
        "CREATE STATISTICS public.audit_logs_lower_description_stat "
        "ON lower(description) FROM audit_logs",
        True,
    )
}


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


def _seed_audit_logs(database_url: str) -> None:
    """ANALYZE builds no statistics from an empty table."""
    tenant_id = str(uuid4())
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, 'audit-statistics', 1000000, 'active')
            """,
            (tenant_id,),
        )
        cursor.execute(
            """
            INSERT INTO audit_logs (
                tenant_id, action, entity_type, entity_id, description
            )
            SELECT %s, 'assistant_created', 'assistant', gen_random_uuid(),
                   'Created assistant ' || (i %% 10)
            FROM generate_series(1, 200) AS i
            """,
            (tenant_id,),
        )


def _statistics(database_url: str) -> dict[str, tuple[str, bool]]:
    """Each statistics object on audit_logs, and whether ANALYZE has built it."""
    with (
        psycopg2.connect(database_url.replace("+psycopg2", "")) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT s.stxname,
                   pg_get_statisticsobjdef(s.oid),
                   EXISTS (
                       SELECT 1 FROM pg_statistic_ext_data d WHERE d.stxoid = s.oid
                   )
            FROM pg_statistic_ext s
            WHERE s.stxrelid = 'audit_logs'::regclass
            """
        )
        return {name: (definition, built) for name, definition, built in cursor}


@pytest.mark.parametrize(
    ("image", "expected"),
    [("pgvector/pgvector:pg16", _STATISTICS), (_POSTGRES_13_IMAGE, {})],
    ids=["pg16", "pg13-no-op"],
)
def test_description_statistics_upgrade_downgrade_and_reupgrade(
    image: str, expected: dict[str, tuple[str, bool]]
) -> None:
    postgres = PostgresContainer(
        image=image,
        username="audit_statistics",
        password="audit_statistics_password",
        dbname="audit_statistics",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        command.upgrade(config, _PREVIOUS_REVISION)
        _seed_audit_logs(database_url)
        assert _statistics(database_url) == {}

        command.upgrade(config, _REVISION)
        assert _statistics(database_url) == expected

        command.downgrade(config, _PREVIOUS_REVISION)
        assert _statistics(database_url) == {}

        command.upgrade(config, _REVISION)
        assert _statistics(database_url) == expected
