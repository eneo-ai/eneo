from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202605170900"
SCHEMA_REVISION = "202605181000"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT version_num FROM alembic_version")
        except psycopg2.errors.UndefinedTable:
            return None
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0])


def _normalize_to_revision(conn, cfg: Config, revision: str) -> None:
    current_revision = _current_revision(conn)
    if current_revision is None:
        command.upgrade(cfg, revision)
    elif current_revision != revision:
        try:
            command.downgrade(cfg, revision)
        except Exception:
            command.upgrade(cfg, revision)

    assert _current_revision(conn) == revision


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def migration_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    _normalize_to_revision(conn, cfg, PRE_REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _columns(conn, table_name: str) -> dict[str, dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, is_nullable, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_name = %s
            """,
            (table_name,),
        )
        rows = cur.fetchall()
    return {
        row[0]: {
            "nullable": row[1],
            "numeric_precision": row[2],
            "numeric_scale": row[3],
        }
        for row in rows
    }


def _index_names(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'crawl_runs'")
        return {row[0] for row in cur.fetchall()}


def _check_constraint_names(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'crawl_runs'::regclass
              AND contype = 'c'
            """
        )
        return {row[0] for row in cur.fetchall()}


class TestEmbeddingUsageCostSchema:
    def test_upgrade_adds_nullable_ratecard_and_crawl_run_usage_shape(
        self, migration_db
    ):
        conn = migration_db["conn"]
        cfg = migration_db["cfg"]

        command.upgrade(cfg, SCHEMA_REVISION)

        embedding_columns = _columns(conn, "embedding_models")
        assert embedding_columns["input_cost_per_token"] == {
            "nullable": "YES",
            "numeric_precision": 20,
            "numeric_scale": 12,
        }
        assert embedding_columns["output_cost_per_token"] == {
            "nullable": "YES",
            "numeric_precision": 20,
            "numeric_scale": 12,
        }

        crawl_run_columns = _columns(conn, "crawl_runs")
        for column_name in (
            "embedding_model_id",
            "embedding_model_name_snapshot",
            "embedding_model_litellm_name_snapshot",
            "embedding_model_provider_snapshot",
            "embedding_input_tokens",
            "embedding_usage_source",
            "embedding_total_cost_usd",
        ):
            assert crawl_run_columns[column_name]["nullable"] == "YES"
        assert crawl_run_columns["embedding_input_cost_per_token_snapshot"] == {
            "nullable": "YES",
            "numeric_precision": 20,
            "numeric_scale": 12,
        }
        assert crawl_run_columns["embedding_total_cost_usd"] == {
            "nullable": "YES",
            "numeric_precision": 20,
            "numeric_scale": 12,
        }

        assert "ck_crawl_runs_embedding_usage_source" in _check_constraint_names(conn)
        assert {
            "idx_crawl_runs_tenant_created_at",
            "idx_crawl_runs_tenant_website_created_at",
        }.issubset(_index_names(conn))

        command.downgrade(cfg, PRE_REVISION)

        embedding_columns = _columns(conn, "embedding_models")
        crawl_run_columns = _columns(conn, "crawl_runs")
        assert "input_cost_per_token" not in embedding_columns
        assert "output_cost_per_token" not in embedding_columns
        assert "embedding_input_tokens" not in crawl_run_columns
        assert "ck_crawl_runs_embedding_usage_source" not in _check_constraint_names(
            conn
        )
        assert "idx_crawl_runs_tenant_created_at" not in _index_names(conn)
        assert "idx_crawl_runs_tenant_website_created_at" not in _index_names(conn)
