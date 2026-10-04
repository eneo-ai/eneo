"""Round-trip flow_retention_holds (202610041000).

After the revision the database matches the ORM declaration (columns, indexes by
normalized definition, constraints and foreign-key delete rules); the downgrade
drops exactly the table and a second upgrade restores it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.flow_tables import FlowRetentionHolds

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610021015"
REVISION = "202610041000"
TABLE = "flow_retention_holds"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
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
    )
    conn.autocommit = True
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield conn, cfg, engine
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
        conn.close()


def _ddl_text(ddl: str) -> str:
    text = ddl.lower().replace("public.", "").replace(" using btree", "")
    return "".join(ch for ch in text if ch not in ' ()"\n;')


def _declared_indexes() -> dict[str, str]:
    return {
        str(index.name): _ddl_text(
            str(
                CreateIndex(index).compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        for index in FlowRetentionHolds.__table__.indexes
    }


def _schema(conn) -> dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (TABLE,),
        )
        columns = {name: (kind, nullable) for name, kind, nullable in cursor.fetchall()}
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s "
            "AND indexname <> %s",
            (TABLE, f"{TABLE}_pkey"),
        )
        indexes = {name: _ddl_text(ddl) for name, ddl in cursor.fetchall()}
        cursor.execute(
            "SELECT conname, contype, confdeltype FROM pg_constraint "
            "WHERE conrelid = to_regclass(%s)",
            (TABLE,),
        )
        constraints = {name: (kind, rule) for name, kind, rule in cursor.fetchall()}
    return {"columns": columns, "indexes": indexes, "constraints": constraints}


def test_upgrade_matches_the_orm_declaration(round_trip_db):
    conn, _cfg, _engine = round_trip_db
    schema = _schema(conn)
    table = FlowRetentionHolds.__table__
    assert set(schema["columns"]) == {column.name for column in table.columns}
    assert {
        name for name, (_, nullable) in schema["columns"].items() if nullable == "NO"
    } == {column.name for column in table.columns if not column.nullable}
    assert schema["columns"]["created_by_actor"][0] == "jsonb"
    assert schema["indexes"] == _declared_indexes()
    assert schema["constraints"] == {
        "flow_retention_holds_pkey": ("p", " "),
        "flow_retention_holds_tenant_id_fkey": ("f", "c"),
        "fk_flow_retention_holds_flow_tenant": ("f", "c"),
        "flow_retention_holds_created_by_user_id_fkey": ("f", "n"),
        "flow_retention_holds_released_by_user_id_fkey": ("f", "n"),
        "ck_flow_retention_holds_reason_length": ("c", " "),
        "ck_flow_retention_holds_ends_after_created": ("c", " "),
        "ck_flow_retention_holds_review_after_created": ("c", " "),
        "ck_flow_retention_holds_release_complete": ("c", " "),
    }
    declared_checks = {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert declared_checks == {
        name for name, (kind, _) in schema["constraints"].items() if kind == "c"
    }


def test_downgrade_drops_the_table_and_upgrade_restores_it(round_trip_db):
    conn, cfg, _engine = round_trip_db
    before = _schema(conn)

    command.downgrade(cfg, PRE_REVISION)
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (TABLE,))
        assert cursor.fetchone()[0] is None

    command.upgrade(cfg, REVISION)
    assert _schema(conn) == before


def _insert_role(conn, tenant_id: str, permissions: list[str]) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO roles (id, name, permissions, tenant_id, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, %s, %s, now(), now())
            RETURNING id
            """,
            (f"retention-role-{uuid4()}", permissions, tenant_id),
        )
        return cursor.fetchone()[0]


def _permissions(conn, role_id: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        return list(cursor.fetchone()[0])


def test_admin_roles_get_both_retention_permissions_and_downgrade_removes_them(
    round_trip_db,
):
    conn, cfg, _engine = round_trip_db
    command.downgrade(cfg, PRE_REVISION)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state) "
            "VALUES (gen_random_uuid(), %s, 1000000, 'active') RETURNING id",
            (f"retention-roles-{uuid4()}",),
        )
        tenant_id = cursor.fetchone()[0]
    admin_role = _insert_role(conn, tenant_id, ["admin", "assistants"])
    partial_role = _insert_role(conn, tenant_id, ["admin", "retention_holds"])
    member_role = _insert_role(conn, tenant_id, ["assistants"])

    command.upgrade(cfg, REVISION)
    assert _permissions(conn, admin_role) == [
        "admin",
        "assistants",
        "retention_manage",
        "retention_holds",
    ]
    assert _permissions(conn, partial_role) == [
        "admin",
        "retention_holds",
        "retention_manage",
    ]
    assert _permissions(conn, member_role) == ["assistants"]

    command.downgrade(cfg, PRE_REVISION)
    assert _permissions(conn, admin_role) == ["admin", "assistants"]
    assert _permissions(conn, partial_role) == ["admin"]
    assert _permissions(conn, member_role) == ["assistants"]
    command.upgrade(cfg, REVISION)
