"""Migration tests for runtime result/attempt step identity ownership.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_runtime_step_identity_migration.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


PRIOR_REVISION = "20260522_builder_lock"
MIGRATION_REVISION = "20260526_flow_step_identity"
_TENANT_NAME_PREFIX = "flow-step-identity-migration-"


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

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRIOR_REVISION)
    _clear_seeded_rows(conn)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _clear_seeded_rows(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tenants WHERE name LIKE %s",
            (_TENANT_NAME_PREFIX + "%",),
        )


def _get_current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    return row[0] if row else None


def _column_nullable(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0] == "YES"


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        return cur.fetchone() is not None


def _row_count(conn, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table_name}")
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _runtime_step_ids(conn, table_name: str) -> list[str | None]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT step_id::text
            FROM {table_name}
            WHERE tenant_id IN (
                SELECT id
                FROM tenants
                WHERE name LIKE %s
            )
            ORDER BY step_order, id
            """,
            (_TENANT_NAME_PREFIX + "%",),
        )
        return [row[0] for row in cur.fetchall()]


def _runtime_step_ids_for_run(
    conn,
    *,
    table_name: str,
    run_id: str,
) -> list[str | None]:
    order_by = (
        "step_order, attempt_no, id"
        if table_name == "flow_step_attempts"
        else "step_order, id"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT step_id::text
            FROM {table_name}
            WHERE flow_run_id = %s
            ORDER BY {order_by}
            """,
            (run_id,),
        )
        return [row[0] for row in cur.fetchall()]


def _insert_runtime_fixture(
    conn,
    *,
    definition_steps: list[dict[str, object]],
    result_rows: list[dict[str, object]],
    attempt_rows: list[dict[str, object]],
) -> dict[str, str]:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()
    tenant_name = f"{_TENANT_NAME_PREFIX}{tenant_id}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id,
                name,
                display_name,
                slug,
                quota_limit,
                privacy_policy,
                domain,
                zitadel_org_id,
                provisioning,
                security_enabled,
                state
            )
            VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, false, false, 'active')
            """,
            (tenant_id, tenant_name, tenant_name, tenant_name[:63], 100000),
        )
        cur.execute(
            """
            INSERT INTO users (
                id,
                username,
                email,
                email_verified,
                salt,
                password,
                is_active,
                state,
                used_tokens,
                tenant_id,
                quota_limit
            )
            VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
            """,
            (
                user_id,
                f"user-{user_id}",
                f"{user_id}@example.test",
                tenant_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO spaces (
                id,
                name,
                description,
                data_retention_days,
                tenant_id,
                user_id
            )
            VALUES (%s, %s, NULL, NULL, %s, NULL)
            """,
            (space_id, "Runtime step identity space", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id,
                name,
                description,
                tenant_id,
                space_id,
                created_by_user_id,
                owner_user_id,
                published_version,
                metadata_json,
                data_retention_days
            )
            VALUES (%s, %s, NULL, %s, %s, %s, %s, 1, NULL, NULL)
            """,
            (
                flow_id,
                "Runtime step identity flow",
                tenant_id,
                space_id,
                user_id,
                user_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_versions (
                flow_id,
                version,
                tenant_id,
                definition_checksum,
                definition_json
            )
            VALUES (%s, 1, %s, 'checksum-runtime-step-identity', %s)
            """,
            (
                flow_id,
                tenant_id,
                Json(
                    {
                        "schema_version": 1,
                        "flow_id": str(flow_id),
                        "name": "Runtime step identity flow",
                        "description": None,
                        "metadata_json": None,
                        "steps": definition_steps,
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                principal_api_key_id,
                user_id,
                tenant_id,
                trace_id,
                status,
                input_payload_json
            )
            VALUES (%s, %s, 1, 'user', %s, NULL, %s, %s, %s, 'completed', '{}')
            """,
            (run_id, flow_id, user_id, user_id, tenant_id, trace_id),
        )
        for row in result_rows:
            cur.execute(
                """
                INSERT INTO flow_step_results (
                    id,
                    flow_run_id,
                    flow_id,
                    tenant_id,
                    step_id,
                    step_order,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'completed')
                """,
                (
                    row.get("id", uuid4()),
                    run_id,
                    flow_id,
                    tenant_id,
                    row.get("step_id"),
                    row["step_order"],
                ),
            )
        for row in attempt_rows:
            cur.execute(
                """
                INSERT INTO flow_step_attempts (
                    id,
                    flow_run_id,
                    flow_id,
                    tenant_id,
                    step_id,
                    step_order,
                    attempt_no,
                    status,
                    started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed', now())
                """,
                (
                    row.get("id", uuid4()),
                    run_id,
                    flow_id,
                    tenant_id,
                    row.get("step_id"),
                    row["step_order"],
                    row.get("attempt_no", 1),
                ),
            )

    return {
        "tenant_id": str(tenant_id),
        "flow_id": str(flow_id),
        "run_id": str(run_id),
    }


def test_upgrade_backfills_snapshot_ids_without_draft_step_fk(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    result_step_id = uuid4()
    attempt_step_id = uuid4()

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(result_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(attempt_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
        ],
        result_rows=[{"step_order": 1}],
        attempt_rows=[{"step_order": 2}],
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == MIGRATION_REVISION
    assert _column_nullable(conn, "flow_step_results", "step_id") is False
    assert _column_nullable(conn, "flow_step_attempts", "step_id") is False
    assert not _constraint_exists(
        conn,
        "flow_step_results",
        "flow_step_results_step_id_fkey",
    )
    assert not _constraint_exists(
        conn,
        "flow_step_attempts",
        "flow_step_attempts_step_id_fkey",
    )
    assert _row_count(conn, "flow_steps") == 0
    assert _runtime_step_ids(conn, "flow_step_results") == [str(result_step_id)]
    assert _runtime_step_ids(conn, "flow_step_attempts") == [str(attempt_step_id)]


def test_upgrade_backfills_multiple_rows_across_published_versions(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    first_result_step_ids = [uuid4(), uuid4(), uuid4()]
    first_attempt_step_ids = [uuid4(), uuid4()]
    second_result_step_id = uuid4()
    second_attempt_step_id = uuid4()

    first = _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(first_result_step_ids[0]),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(first_result_step_ids[1]),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
            {
                "step_id": str(first_result_step_ids[2]),
                "assistant_id": str(uuid4()),
                "step_order": 3,
            },
            {
                "step_id": str(first_attempt_step_ids[0]),
                "assistant_id": str(uuid4()),
                "step_order": 4,
            },
            {
                "step_id": str(first_attempt_step_ids[1]),
                "assistant_id": str(uuid4()),
                "step_order": 5,
            },
        ],
        result_rows=[
            {"step_order": 1},
            {"step_order": 2},
            {"step_order": 3},
        ],
        attempt_rows=[
            {"step_order": 4, "attempt_no": 1},
            {"step_order": 5, "attempt_no": 2},
        ],
    )
    second = _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(second_result_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(second_attempt_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
        ],
        result_rows=[{"step_order": 1}],
        attempt_rows=[{"step_order": 2}],
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _runtime_step_ids_for_run(
        conn, table_name="flow_step_results", run_id=first["run_id"]
    ) == [str(step_id) for step_id in first_result_step_ids]
    assert _runtime_step_ids_for_run(
        conn, table_name="flow_step_attempts", run_id=first["run_id"]
    ) == [str(step_id) for step_id in first_attempt_step_ids]
    assert _runtime_step_ids_for_run(
        conn, table_name="flow_step_results", run_id=second["run_id"]
    ) == [str(second_result_step_id)]
    assert _runtime_step_ids_for_run(
        conn, table_name="flow_step_attempts", run_id=second["run_id"]
    ) == [str(second_attempt_step_id)]


def test_upgrade_aborts_when_null_step_id_cannot_be_recovered(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": "not-a-uuid",
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
        ],
        result_rows=[{"step_order": 1}],
        attempt_rows=[],
    )

    with pytest.raises(Exception, match="not recoverable"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _column_nullable(conn, "flow_step_results", "step_id") is True
    assert _constraint_exists(
        conn, "flow_step_results", "flow_step_results_step_id_fkey"
    )


def test_upgrade_rejects_duplicate_recovered_result_step_ids(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    duplicate_step_id = uuid4()

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(duplicate_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(duplicate_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
        ],
        result_rows=[{"step_order": 1}, {"step_order": 2}],
        attempt_rows=[],
    )

    with pytest.raises(Exception, match="uq_flow_step_results_run_step"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _constraint_exists(
        conn, "flow_step_results", "flow_step_results_step_id_fkey"
    )


def test_upgrade_rejects_duplicate_recovered_attempt_step_ids(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    duplicate_step_id = uuid4()

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(duplicate_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(duplicate_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
        ],
        result_rows=[],
        attempt_rows=[
            {"step_order": 1, "attempt_no": 1},
            {"step_order": 2, "attempt_no": 1},
        ],
    )

    with pytest.raises(Exception, match="uq_flow_step_attempts_run_step_attempt"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _constraint_exists(
        conn, "flow_step_attempts", "flow_step_attempts_step_id_fkey"
    )


def test_upgrade_rejects_ambiguous_snapshot_step_order_mapping(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(uuid4()),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(uuid4()),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
        ],
        result_rows=[{"step_order": 1}],
        attempt_rows=[],
    )

    with pytest.raises(Exception, match="multiple step_id values"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _constraint_exists(
        conn, "flow_step_results", "flow_step_results_step_id_fkey"
    )


def test_upgrade_does_not_recover_from_other_tenant_snapshot(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(uuid4()),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
        ],
        result_rows=[],
        attempt_rows=[],
    )
    _insert_runtime_fixture(
        conn,
        definition_steps=[],
        result_rows=[{"step_order": 1}],
        attempt_rows=[],
    )

    with pytest.raises(Exception, match="not recoverable"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _constraint_exists(
        conn, "flow_step_results", "flow_step_results_step_id_fkey"
    )


def test_downgrade_nulls_orphan_ids_before_restoring_draft_fk(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    result_step_id = uuid4()
    attempt_step_id = uuid4()

    _insert_runtime_fixture(
        conn,
        definition_steps=[
            {
                "step_id": str(result_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 1,
            },
            {
                "step_id": str(attempt_step_id),
                "assistant_id": str(uuid4()),
                "step_order": 2,
            },
        ],
        result_rows=[{"step_order": 1}],
        attempt_rows=[{"step_order": 2}],
    )

    command.upgrade(cfg, MIGRATION_REVISION)
    assert _runtime_step_ids(conn, "flow_step_results") == [str(result_step_id)]
    assert _runtime_step_ids(conn, "flow_step_attempts") == [str(attempt_step_id)]

    command.downgrade(cfg, PRIOR_REVISION)

    assert _get_current_revision(conn) == PRIOR_REVISION
    assert _column_nullable(conn, "flow_step_results", "step_id") is True
    assert _column_nullable(conn, "flow_step_attempts", "step_id") is True
    assert _constraint_exists(
        conn, "flow_step_results", "flow_step_results_step_id_fkey"
    )
    assert _constraint_exists(
        conn, "flow_step_attempts", "flow_step_attempts_step_id_fkey"
    )
    assert _runtime_step_ids(conn, "flow_step_results") == [None]
    assert _runtime_step_ids(conn, "flow_step_attempts") == [None]

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _runtime_step_ids(conn, "flow_step_results") == [str(result_step_id)]
    assert _runtime_step_ids(conn, "flow_step_attempts") == [str(attempt_step_id)]
