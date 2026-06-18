"""Focused coverage for residual global model repair.

Run with:
    pytest -m migration_isolation \
        tests/integration/migrations/test_model_tenant_required_migration.py -v
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def repaired_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    space_a = uuid4()
    app_a = uuid4()
    global_transcription = uuid4()

    try:
        command.upgrade(cfg, "202605251000")
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                DECLARE r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = 'public'
                          AND tablename != 'alembic_version'
                    ) LOOP
                        EXECUTE 'TRUNCATE TABLE ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
                """
            )
            cur.execute(
                """
                INSERT INTO tenants (
                    id, name, slug, quota_limit, state, api_credentials,
                    federation_config, crawler_settings, api_key_policy,
                    favorite_providers
                )
                VALUES
                    (%s, 'tenant-a', 'tenant-a', 1000000, 'active', '{}', '{}', '{}', '{}', '[]'),
                    (%s, 'tenant-b', 'tenant-b', 1000000, 'active', '{}', '{}', '{}', '{}', '[]')
                """,
                (tenant_a, tenant_b),
            )
            cur.execute(
                """
                INSERT INTO users (
                    id, username, email, state, used_tokens, tenant_id
                )
                VALUES (%s, 'admin-a', 'admin-a@example.com', 'active', 0, %s)
                """,
                (user_a, tenant_a),
            )
            cur.execute(
                """
                INSERT INTO spaces (
                    id, name, description, data_retention_days, tenant_id,
                    user_id
                )
                VALUES (%s, 'Tenant A space', NULL, NULL, %s, NULL)
                """,
                (space_a, tenant_a),
            )
            cur.execute(
                """
                INSERT INTO transcription_models (
                    id, name, model_name, nickname, open_source, is_deprecated,
                    family, stability, hosting, description, org, base_url,
                    cost_per_minute, tenant_id, provider_id, is_enabled,
                    is_default, deleted_at
                )
                VALUES (
                    %s, 'KB-Whisper', 'kb-whisper', 'KB-Whisper', false, false,
                    'openai', 'stable', 'swe', 'Berget-hosted transcription',
                    'Berget', 'https://api.berget.ai/v1', 0.006,
                    NULL, NULL, true, true, NULL
                )
                """,
                (global_transcription,),
            )
            cur.execute(
                """
                INSERT INTO apps (
                    id, name, description, completion_model_kwargs, published,
                    data_retention_days, tenant_id, user_id, space_id,
                    transcription_model_id
                )
                VALUES (%s, 'App A', NULL, '{}', false, NULL, %s, %s, %s, %s)
                """,
                (app_a, tenant_a, user_a, space_a, global_transcription),
            )
            cur.execute(
                """
                INSERT INTO spaces_transcription_models (
                    space_id, transcription_model_id
                )
                VALUES (%s, %s)
                """,
                (space_a, global_transcription),
            )

        command.upgrade(cfg, "head")
        yield {
            "conn": conn,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "app_a": app_a,
            "space_a": space_a,
            "global_transcription": global_transcription,
        }
    finally:
        conn.close()


def test_residual_global_transcription_models_are_repaired(repaired_db):
    conn = repaired_db["conn"]
    tenant_a = repaired_db["tenant_a"]
    tenant_b = repaired_db["tenant_b"]
    app_a = repaired_db["app_a"]
    space_a = repaired_db["space_a"]
    global_transcription = repaired_db["global_transcription"]

    with conn.cursor() as cur:
        for table in (
            "completion_models",
            "embedding_models",
            "transcription_models",
        ):
            cur.execute(
                f"""
                SELECT count(*)
                FROM {table}
                WHERE tenant_id IS NULL OR provider_id IS NULL
                """
            )
            assert cur.fetchone()[0] == 0

        cur.execute(
            """
            SELECT tm.id, tm.tenant_id, tm.provider_id, tm.is_enabled, tm.is_default,
                   mp.name, mp.provider_type, mp.is_active, mp.config->>'endpoint',
                   mp.credentials
            FROM transcription_models tm
            JOIN model_providers mp ON mp.id = tm.provider_id
            WHERE tm.model_name = 'kb-whisper'
            ORDER BY tm.tenant_id
            """
        )
        rows = cur.fetchall()
        assert {row[1] for row in rows} == {str(tenant_a), str(tenant_b)}
        assert all(row[2] is not None for row in rows)
        assert all(row[3] is False for row in rows)
        assert all(row[4] is False for row in rows)
        assert all(row[5] == "Berget.ai" for row in rows)
        assert all(row[6] == "hosted_vllm" for row in rows)
        assert all(row[7] is False for row in rows)
        assert all(row[8] == "https://api.berget.ai/v1" for row in rows)
        assert all(row[9] == {} for row in rows)

        tenant_a_model_id = next(row[0] for row in rows if row[1] == str(tenant_a))
        cur.execute(
            "SELECT transcription_model_id FROM apps WHERE id = %s",
            (app_a,),
        )
        assert cur.fetchone()[0] == tenant_a_model_id

        cur.execute(
            """
            SELECT transcription_model_id
            FROM spaces_transcription_models
            WHERE space_id = %s
            """,
            (space_a,),
        )
        assert cur.fetchone()[0] == tenant_a_model_id

        cur.execute(
            "SELECT 1 FROM transcription_models WHERE id = %s",
            (global_transcription,),
        )
        assert cur.fetchone() is None


def test_model_owner_columns_are_not_nullable(repaired_db):
    conn = repaired_db["conn"]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name IN (
                'completion_models',
                'embedding_models',
                'transcription_models'
            )
              AND column_name IN ('tenant_id', 'provider_id')
            """
        )
        assert {row[2] for row in cur.fetchall()} == {"NO"}
