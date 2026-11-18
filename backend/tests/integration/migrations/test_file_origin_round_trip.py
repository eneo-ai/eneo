"""Round trip for 202611181900: where a Flow file came from.

After the revision the three origin columns of ``files`` match the ORM
declaration, have no foreign key, and the check refuses every incomplete
origin exactly as the model's check does. The downgrade removes the columns
and the check and keeps the rows.

    pytest -m migration_isolation \
        tests/integration/migrations/test_file_origin_round_trip.py
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import psycopg2.errors
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.files_table import Files
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611111000"
REVISION = "202611181900"
ORIGIN_COLUMNS = ("origin_space_id", "origin_flow_id", "origin_flow_run_id")
CHECK = "ck_files_origin"


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
    try:
        with at_revision(cfg, REVISION):
            yield conn, cfg
    finally:
        conn.close()


def _origin_schema(conn) -> dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
            "pg_get_expr(d.adbin, d.adrelid), col_description(a.attrelid, a.attnum) "
            "FROM pg_attribute a "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE a.attrelid = 'files'::regclass AND a.attnum > 0 "
            "AND NOT a.attisdropped AND a.attname = ANY(%s)",
            (list(ORIGIN_COLUMNS),),
        )
        columns = {
            name: (kind, not_null, default, comment)
            for name, kind, not_null, default, comment in cursor.fetchall()
        }
        cursor.execute(
            "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
            "WHERE conrelid = 'files'::regclass AND conname = %s",
            (CHECK,),
        )
        check = cursor.fetchone()
        # Any constraint other than the check that names an origin column
        # (a foreign key, a unique key) would make the origin more than a fact.
        cursor.execute(
            "SELECT c.conname FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.conrelid = 'files'::regclass AND c.conname <> %s "
            "AND a.attname = ANY(%s)",
            (CHECK, list(ORIGIN_COLUMNS)),
        )
        other_constraints = sorted(row[0] for row in cursor.fetchall())
        cursor.execute(
            "SELECT i.relname FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = ANY(x.indkey) "
            "WHERE x.indrelid = 'files'::regclass AND a.attname = ANY(%s)",
            (list(ORIGIN_COLUMNS),),
        )
        indexes = sorted(row[0] for row in cursor.fetchall())
    return {
        "columns": columns,
        "check": check,
        "other_constraints": other_constraints,
        "indexes": indexes,
    }


def _declared_check() -> sa.CheckConstraint:
    return next(
        constraint
        for constraint in Files.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint) and constraint.name == CHECK
    )


def _owner(conn) -> tuple[UUID, UUID]:
    tenant_id, user_id = uuid4(), uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state)"
            " VALUES (%s, %s, 1000000, 'active')",
            (str(tenant_id), f"file-origin-{tenant_id.hex[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users (id, tenant_id, email, used_tokens, state)"
            " VALUES (%s, %s, %s, 0, 'active')",
            (str(user_id), str(tenant_id), f"{user_id.hex}@example.test"),
        )
    return tenant_id, user_id


def _insert_file(
    conn,
    *,
    tenant_id: UUID,
    user_id: UUID,
    origin: tuple[UUID | None, UUID | None, UUID | None] = (None, None, None),
) -> UUID:
    columns = ", ".join(ORIGIN_COLUMNS)
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO files (name, owner_type, owner_user_id, tenant_id, {columns})"
            " VALUES ('origin.txt', 'user', %s, %s, %s, %s, %s) RETURNING id",
            (
                str(user_id),
                str(tenant_id),
                *(None if value is None else str(value) for value in origin),
            ),
        )
        return cursor.fetchone()[0]


def test_upgrade_matches_the_model_and_refuses_every_incomplete_origin(
    round_trip_db,
):
    conn, _cfg = round_trip_db
    schema = _origin_schema(conn)
    table = Files.__table__
    for name in ORIGIN_COLUMNS:
        column = table.c[name]
        assert column.nullable
        assert isinstance(column.type, sa.Uuid)
        assert column.comment
        assert not column.foreign_keys
    assert schema["columns"] == {
        name: ("uuid", False, None, table.c[name].comment) for name in ORIGIN_COLUMNS
    }
    assert schema["other_constraints"] == []
    assert schema["indexes"] == []
    definition, validated = schema["check"]
    assert validated is True
    declared = _declared_check()
    compiled = str(
        declared.sqltext.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    tenant_id, user_id = _owner(conn)
    space_id, flow_id, run_id = uuid4(), uuid4(), uuid4()
    accepted: set[tuple[bool, bool, bool]] = set()
    model_accepts: set[tuple[bool, bool, bool]] = set()
    for present in product((False, True), repeat=3):
        origin = tuple(
            value if is_set else None
            for value, is_set in zip((space_id, flow_id, run_id), present, strict=True)
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT ({compiled}) FROM (SELECT %s::uuid AS origin_space_id, "
                "%s::uuid AS origin_flow_id, %s::uuid AS origin_flow_run_id) AS row",
                tuple(None if value is None else str(value) for value in origin),
            )
            if cursor.fetchone()[0]:
                model_accepts.add(present)
        try:
            _insert_file(conn, tenant_id=tenant_id, user_id=user_id, origin=origin)
        except psycopg2.errors.CheckViolation as exc:
            assert exc.diag.constraint_name == CHECK
        else:
            accepted.add(present)

    # No origin, an upload's origin (space and flow), or a run file's origin.
    assert accepted == {
        (False, False, False),
        (True, True, False),
        (True, True, True),
    }
    assert model_accepts == accepted
    assert "IS NULL" in definition and "IS NOT NULL" in definition


def test_downgrade_removes_the_origin_and_keeps_the_files(round_trip_db):
    conn, cfg = round_trip_db
    tenant_id, user_id = _owner(conn)
    file_id = _insert_file(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        origin=(uuid4(), uuid4(), uuid4()),
    )

    command.downgrade(cfg, PRE_REVISION)
    assert _origin_schema(conn) == {
        "columns": {},
        "check": None,
        "other_constraints": [],
        "indexes": [],
    }
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM files WHERE id = %s", (file_id,))
        assert cursor.fetchone() == (1,)

    # Recorded origins are not restored: NULL means "not recorded".
    command.upgrade(cfg, REVISION)
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {', '.join(ORIGIN_COLUMNS)} FROM files WHERE id = %s",
            (file_id,),
        )
        assert cursor.fetchone() == (None, None, None)
