"""Migration tests for Flow runtime upload provenance bindings.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_runtime_upload_bindings.py -q
"""

from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260607_step_input_attempt"
MIGRATION_REVISION = "20260607_flow_runtime_uploads"
RUNTIME_UPLOADS_TABLE = "flow_runtime_uploaded_files"
STEP_INPUT_RUNTIME_UPLOAD_FK = "fk_flow_run_step_input_files_runtime_upload"


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

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        command.upgrade(cfg, "head")
        conn.close()


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        return cur.fetchone()[0] is not None


def _constraint_definition(conn, table_name: str, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _insert_attached_runtime_file(
    conn,
    *,
    tenant_id: UUID,
    user_id: UUID,
    space_id: UUID,
    flow_id: UUID,
    flow_run_id: UUID,
    step_id: UUID,
    file_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (str(tenant_id), f"runtime-upload-migration-{tenant_id}"),
        )
        cur.execute(
            """
            INSERT INTO users (
                id,
                email,
                state,
                tenant_id,
                quota_limit,
                used_tokens
            )
            VALUES (%s, %s, 'active', %s, NULL, 0)
            """,
            (str(user_id), f"{user_id}@example.invalid", str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, 'Runtime Upload Migration Space', %s, NULL)
            """,
            (str(space_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id,
                name,
                tenant_id,
                space_id,
                created_by_user_id,
                owner_user_id
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                str(flow_id),
                f"Runtime Upload Migration Flow {flow_id}",
                str(tenant_id),
                str(space_id),
                str(user_id),
                str(user_id),
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
            VALUES (%s, 1, %s, 'checksum', '{}'::jsonb)
            """,
            (str(flow_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                tenant_id,
                status
            )
            VALUES (%s, %s, 1, 'user', %s, %s, 'queued')
            """,
            (str(flow_run_id), str(flow_id), str(user_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO files (
                id,
                name,
                checksum,
                size,
                mimetype,
                file_type,
                owner_type,
                owner_user_id,
                tenant_id
            )
            VALUES (
                %s,
                'source.pdf',
                'file-checksum',
                1024,
                'application/pdf',
                'document',
                'user',
                %s,
                %s
            )
            """,
            (str(file_id), str(user_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO flow_run_step_input_files (
                flow_run_id,
                flow_id,
                tenant_id,
                step_id,
                step_order,
                attempt_no,
                file_id,
                ordinal
            )
            VALUES (%s, %s, %s, %s, 1, 1, %s, 0)
            """,
            (
                str(flow_run_id),
                str(flow_id),
                str(tenant_id),
                str(step_id),
                str(file_id),
            ),
        )


def _insert_additional_flow_attachment(
    conn,
    *,
    tenant_id: UUID,
    user_id: UUID,
    space_id: UUID,
    flow_id: UUID,
    flow_run_id: UUID,
    step_id: UUID,
    file_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flows (
                id,
                name,
                tenant_id,
                space_id,
                created_by_user_id,
                owner_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(flow_id),
                f"Runtime Upload Migration Flow {flow_id}",
                str(tenant_id),
                str(space_id),
                str(user_id),
                str(user_id),
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
            VALUES (%s, 1, %s, 'checksum', '{}'::jsonb)
            """,
            (str(flow_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                tenant_id,
                status
            )
            VALUES (%s, %s, 1, 'user', %s, %s, 'queued')
            """,
            (str(flow_run_id), str(flow_id), str(user_id), str(tenant_id)),
        )
        cur.execute(
            """
            INSERT INTO flow_run_step_input_files (
                flow_run_id,
                flow_id,
                tenant_id,
                step_id,
                step_order,
                attempt_no,
                file_id,
                ordinal
            )
            VALUES (%s, %s, %s, %s, 1, 1, %s, 0)
            """,
            (
                str(flow_run_id),
                str(flow_id),
                str(tenant_id),
                str(step_id),
                str(file_id),
            ),
        )


def _runtime_upload_row(conn, file_id: UUID) -> tuple[str, str, str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                flow_id::text,
                tenant_id::text,
                uploaded_for_step_id::text,
                owner_type,
                owner_user_id::text
            FROM flow_runtime_uploaded_files
            WHERE file_id = %s
            """,
            (str(file_id),),
        )
        row = cur.fetchone()
    assert row is not None
    return row


def _delete_step_inputs_for_file(conn, file_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM flow_run_step_input_files WHERE file_id = %s",
            (str(file_id),),
        )


def test_upgrade_backfills_runtime_upload_binding_and_downgrade_drops_it(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    flow_run_id = uuid4()
    step_id = uuid4()
    file_id = uuid4()

    assert not _table_exists(conn, RUNTIME_UPLOADS_TABLE)
    assert (
        _constraint_definition(
            conn,
            "flow_run_step_input_files",
            STEP_INPUT_RUNTIME_UPLOAD_FK,
        )
        is None
    )

    _insert_attached_runtime_file(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        flow_id=flow_id,
        flow_run_id=flow_run_id,
        step_id=step_id,
        file_id=file_id,
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _table_exists(conn, RUNTIME_UPLOADS_TABLE)
    assert _runtime_upload_row(conn, file_id) == (
        str(flow_id),
        str(tenant_id),
        str(step_id),
        "user",
        str(user_id),
    )
    fk_definition = _constraint_definition(
        conn,
        "flow_run_step_input_files",
        STEP_INPUT_RUNTIME_UPLOAD_FK,
    )
    assert fk_definition is not None
    assert "flow_runtime_uploaded_files" in fk_definition

    command.downgrade(cfg, PRIOR_REVISION)

    assert not _table_exists(conn, RUNTIME_UPLOADS_TABLE)
    assert (
        _constraint_definition(
            conn,
            "flow_run_step_input_files",
            STEP_INPUT_RUNTIME_UPLOAD_FK,
        )
        is None
    )


def test_upgrade_aborts_when_existing_runtime_file_spans_flows(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    file_id = uuid4()
    first_flow_id = uuid4()
    second_flow_id = uuid4()

    _insert_attached_runtime_file(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        flow_id=first_flow_id,
        flow_run_id=uuid4(),
        step_id=uuid4(),
        file_id=file_id,
    )
    _insert_additional_flow_attachment(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        flow_id=second_flow_id,
        flow_run_id=uuid4(),
        step_id=uuid4(),
        file_id=file_id,
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.upgrade(cfg, MIGRATION_REVISION)

    message = str(exc_info.value)
    assert "Cannot backfill flow_runtime_uploaded_files" in message
    assert str(file_id) in message
    _delete_step_inputs_for_file(conn, file_id)
