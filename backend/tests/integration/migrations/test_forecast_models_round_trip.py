"""Round-trip test for the forecast_models migration.

``202610221000`` creates the catalog and binds every existing Forecast source
to its tenant's ``default`` forecast model, under a tool service provider,
without changing anything else on the source. The downgrade removes both, and
the provider unless another model uses it.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_forecast_models_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import psycopg2.extras
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610201000"
REVISION = "202610221000"
TOOL_SERVICE = "eneo_tool_service"
# What the migration must leave as it was on a Forecast source.
SOURCE_COLUMNS = (
    "name",
    "is_enabled",
    "audience",
    "audience_priority",
    "security_classification_id",
    "http_url",
    "updated_at",
)


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override shared cleanup_database so schema revisions persist across
    downgrade/upgrade cycles within this module.
    """
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override shared seed_default_models — this module seeds its own data."""
    yield


@pytest.fixture
def round_trip_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True

    command.upgrade(cfg, REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _one(conn, sql: str, *params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _all(conn, sql: str, *params) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _insert_server(conn, tenant_id, name, tool, purpose, **columns):
    values = {
        "tenant_id": tenant_id,
        "name": name,
        "http_url": f"http://tool-runtime:3010/mcp/{tool}",
        "http_auth_type": "bundled",
        "purpose": purpose,
        **columns,
    }
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return _one(
        conn,
        f"INSERT INTO mcp_servers ({names}) VALUES ({marks}) RETURNING id",
        *values.values(),
    )["id"]


def _seed(conn) -> dict:
    """One tenant with a Forecast source and one without, at PRE_REVISION."""
    suffix = uuid4().hex[:8]
    with_source = _one(
        conn,
        "INSERT INTO tenants (name, quota_limit, state) "
        "VALUES (%s, 1000000, 'active') RETURNING id",
        f"forecast-{suffix}",
    )["id"]
    without = _one(
        conn,
        "INSERT INTO tenants (name, quota_limit, state) "
        "VALUES (%s, 1000000, 'active') RETURNING id",
        f"no-forecast-{suffix}",
    )["id"]
    own_classification = _one(
        conn,
        "INSERT INTO security_classifications (name, security_level, tenant_id) "
        "VALUES ('Confidential', 3, %s) RETURNING id",
        with_source,
    )["id"]
    group = _one(
        conn,
        "INSERT INTO user_groups (name, tenant_id) VALUES ('Analysts', %s) "
        "RETURNING id",
        with_source,
    )["id"]
    source = _insert_server(
        conn,
        with_source,
        "Prognos",
        "forecast",
        "forecast",
        is_enabled=True,
        audience="groups",
        audience_priority=5,
        security_classification_id=own_classification,
    )
    _one(
        conn,
        "INSERT INTO mcp_server_user_groups (mcp_server_id, user_group_id) "
        "VALUES (%s, %s) RETURNING mcp_server_id",
        source,
        group,
    )
    compute = _insert_server(
        conn, with_source, "Compute", "compute", "compute", is_enabled=True
    )
    _insert_server(conn, without, "Compute", "compute", "compute", is_enabled=True)
    return {
        "tenant": with_source,
        "other_tenant": without,
        "source": source,
        "compute": compute,
        "group": group,
    }


def _source(conn, source_id) -> dict:
    return dict(
        _one(
            conn,
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM mcp_servers WHERE id = %s",
            source_id,
        )
    )


def _providers(conn, tenant_id) -> list[dict]:
    return _all(
        conn,
        "SELECT id, name, credentials, config, is_active FROM model_providers "
        "WHERE tenant_id = %s AND provider_type = %s",
        tenant_id,
        TOOL_SERVICE,
    )


def _models(conn, tenant_id) -> list[dict]:
    return _all(
        conn,
        "SELECT id, provider_id, name, nickname, org, open_source, is_enabled, "
        "is_deprecated, security_classification_id, deleted_at "
        "FROM forecast_models WHERE tenant_id = %s",
        tenant_id,
    )


def _forecast_model_id(conn, server_id):
    return _one(
        conn, "SELECT forecast_model_id FROM mcp_servers WHERE id = %s", server_id
    )["forecast_model_id"]


def _relation_exists(conn, name: str) -> bool:
    return _one(conn, "SELECT to_regclass(%s) IS NOT NULL AS found", name)["found"]


def _column_exists(conn) -> bool:
    return (
        _one(
            conn,
            "SELECT 1 AS found FROM information_schema.columns "
            "WHERE table_name = 'mcp_servers' AND column_name = 'forecast_model_id'",
        )
        is not None
    )


def _assert_bound(conn, seeded: dict, before: dict) -> None:
    [provider] = _providers(conn, seeded["tenant"])
    assert provider["name"] == "Eneo tool service"
    assert (provider["credentials"], provider["config"]) == ({}, {})
    assert provider["is_active"] is True
    [model] = _models(conn, seeded["tenant"])
    assert model["provider_id"] == provider["id"]
    assert {key: model[key] for key in model if key not in ("id", "provider_id")} == {
        "name": "default",
        "nickname": "Timestral",
        "org": "Mistral AI",
        "open_source": True,
        "is_enabled": True,
        "is_deprecated": False,
        "security_classification_id": None,
        "deleted_at": None,
    }
    assert _forecast_model_id(conn, seeded["source"]) == model["id"]
    # Nothing else on the source changed, audience included.
    assert _source(conn, seeded["source"]) == before
    assert _all(
        conn,
        "SELECT user_group_id FROM mcp_server_user_groups WHERE mcp_server_id = %s",
        seeded["source"],
    ) == [{"user_group_id": seeded["group"]}]
    assert _forecast_model_id(conn, seeded["compute"]) is None
    assert _providers(conn, seeded["other_tenant"]) == []
    assert _models(conn, seeded["other_tenant"]) == []


class TestForecastModelsRoundTrip:
    def test_upgrade_binds_each_source_to_its_tenants_default_model(
        self, round_trip_db
    ):
        conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
        command.downgrade(cfg, PRE_REVISION)
        seeded = _seed(conn)
        before = _source(conn, seeded["source"])

        command.upgrade(cfg, REVISION)

        assert _one(conn, "SELECT version_num FROM alembic_version")["version_num"] == (
            REVISION
        )
        _assert_bound(conn, seeded, before)

    def test_downgrade_removes_the_catalog_and_the_unused_provider(self, round_trip_db):
        conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
        command.downgrade(cfg, PRE_REVISION)
        seeded = _seed(conn)
        kept = _seed(conn)
        before = _source(conn, seeded["source"])
        command.upgrade(cfg, REVISION)
        # A provider another model type uses survives: deleting it would
        # cascade to that model.
        [shared] = _providers(conn, kept["tenant"])
        _one(
            conn,
            "INSERT INTO image_models (tenant_id, provider_id, name, nickname, "
            "family, stability, hosting) VALUES (%s, %s, 'img', 'Img', 'openai', "
            "'stable', 'swe') RETURNING id",
            kept["tenant"],
            shared["id"],
        )

        command.downgrade(cfg, PRE_REVISION)

        assert not _relation_exists(conn, "public.forecast_models")
        assert not _column_exists(conn)
        assert _providers(conn, seeded["tenant"]) == []
        assert [p["id"] for p in _providers(conn, kept["tenant"])] == [shared["id"]]
        assert _source(conn, seeded["source"]) == before

    def test_upgrade_after_a_downgrade_binds_again(self, round_trip_db):
        conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
        command.downgrade(cfg, PRE_REVISION)
        seeded = _seed(conn)
        before = _source(conn, seeded["source"])

        command.upgrade(cfg, REVISION)
        command.downgrade(cfg, PRE_REVISION)
        command.upgrade(cfg, REVISION)

        _assert_bound(conn, seeded, before)
