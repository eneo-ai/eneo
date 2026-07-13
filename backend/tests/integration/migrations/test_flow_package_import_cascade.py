"""Fresh-chain PostgreSQL contract for Flow package import ownership."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_PACKAGE_REVISION = "20260518_flow_resource_bindings"
PACKAGE_REVISION = "20260519_flow_package_imports"
CURRENT_HEAD = "202607111200_file_tenant_fks"


@dataclass(frozen=True)
class _GraphIds:
    tenant: UUID
    user: UUID
    space: UUID
    flow: UUID
    successful_import: UUID
    failed_import: UUID | None
    audit: UUID | None


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    yield


@pytest.fixture
def fresh_chain_db(test_settings) -> Iterator[tuple[PsycopgConnection, Config]]:
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    reset_public_schema(conn)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_fresh_chain_cascades_operational_import_rows_and_replays(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    command.upgrade(cfg, PACKAGE_REVISION)
    assert current_revisions(conn) == {PACKAGE_REVISION}
    _assert_flow_import_fk_and_index(conn)

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    _assert_flow_import_fk_and_index(conn)

    retained_audit_graph = _seed_graph(
        conn,
        suffix="retained-audit",
        include_failed=True,
        include_audit=True,
    )
    assert retained_audit_graph.failed_import is not None
    assert retained_audit_graph.audit is not None
    _assert_flow_identity_mismatches_are_rejected(conn, retained_audit_graph)

    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM flows WHERE id = %s",
            (retained_audit_graph.flow,),
        )
        cursor.execute(
            """
            SELECT id
            FROM flow_package_imports
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (
                [
                    retained_audit_graph.successful_import,
                    retained_audit_graph.failed_import,
                ],
            ),
        )
        assert {str(row[0]) for row in cursor.fetchall()} == {
            str(retained_audit_graph.failed_import)
        }
        cursor.execute(
            "SELECT count(*) FROM audit_logs WHERE id = %s",
            (retained_audit_graph.audit,),
        )
        assert cursor.fetchone() == (1,)

        cursor.execute(
            "DELETE FROM spaces WHERE id = %s",
            (retained_audit_graph.space,),
        )
        cursor.execute(
            "SELECT count(*) FROM flow_package_imports WHERE id = %s",
            (retained_audit_graph.failed_import,),
        )
        assert cursor.fetchone() == (0,)
        cursor.execute(
            "SELECT count(*) FROM audit_logs WHERE id = %s",
            (retained_audit_graph.audit,),
        )
        assert cursor.fetchone() == (1,)

    tenant_graph = _seed_graph(
        conn,
        suffix="tenant-cascade",
        include_failed=False,
        include_audit=False,
    )
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_graph.tenant,))
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM spaces WHERE id = %s),
                (SELECT count(*) FROM flows WHERE id = %s),
                (SELECT count(*) FROM flow_package_imports WHERE id = %s)
            """,
            (
                tenant_graph.space,
                tenant_graph.flow,
                tenant_graph.successful_import,
            ),
        )
        assert cursor.fetchone() == (0, 0, 0)
        cursor.execute(
            "DELETE FROM tenants WHERE id = %s",
            (retained_audit_graph.tenant,),
        )

    command.downgrade(cfg, PRE_PACKAGE_REVISION)
    assert PRE_PACKAGE_REVISION in current_revisions(conn)
    assert not _table_exists(conn, "flow_package_imports")
    assert not _constraint_exists(
        conn,
        table_name="flows",
        constraint_name="uq_flows_id_tenant_id_space_id",
    )

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    _assert_flow_import_fk_and_index(conn)


def _seed_graph(
    conn: PsycopgConnection,
    *,
    suffix: str,
    include_failed: bool,
    include_audit: bool,
) -> _GraphIds:
    ids = _GraphIds(
        tenant=uuid4(),
        user=uuid4(),
        space=uuid4(),
        flow=uuid4(),
        successful_import=uuid4(),
        failed_import=uuid4() if include_failed else None,
        audit=uuid4() if include_audit else None,
    )
    checksum = "a" * 64
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (ids.tenant, f"flow-package-{suffix}-{ids.tenant}"),
        )
        cursor.execute(
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
            (ids.user, f"{ids.user}@example.invalid", ids.tenant),
        )
        cursor.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, %s, %s, NULL)
            """,
            (ids.space, f"Flow package {suffix}", ids.tenant),
        )
        cursor.execute(
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
                ids.flow,
                f"Flow package {suffix}",
                ids.tenant,
                ids.space,
                ids.user,
                ids.user,
            ),
        )
        cursor.execute(
            """
            INSERT INTO flow_package_imports (
                id,
                tenant_id,
                space_id,
                flow_id,
                created_by_user_id,
                package_id,
                package_version,
                content_checksum,
                source,
                status,
                import_plan_json,
                selected_mappings_json,
                failure_json
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, '1.0.0', %s,
                'file_upload', 'draft_created', '{}'::jsonb, '{}'::jsonb, NULL
            )
            """,
            (
                ids.successful_import,
                ids.tenant,
                ids.space,
                ids.flow,
                ids.user,
                f"se.test.{suffix}",
                checksum,
            ),
        )
        if ids.failed_import is not None:
            cursor.execute(
                """
                INSERT INTO flow_package_imports (
                    id,
                    tenant_id,
                    space_id,
                    flow_id,
                    created_by_user_id,
                    package_id,
                    package_version,
                    content_checksum,
                    source,
                    status,
                    import_plan_json,
                    selected_mappings_json,
                    failure_json
                )
                VALUES (
                    %s, %s, %s, NULL, %s, %s, '1.0.0', %s,
                    'file_upload', 'failed', '{}'::jsonb, '{}'::jsonb,
                    '{"code":"synthetic_failure"}'::jsonb
                )
                """,
                (
                    ids.failed_import,
                    ids.tenant,
                    ids.space,
                    ids.user,
                    f"se.test.{suffix}.failed",
                    checksum,
                ),
            )
        if ids.audit is not None:
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    id,
                    tenant_id,
                    actor_id,
                    actor_type,
                    action,
                    entity_type,
                    entity_id,
                    description,
                    metadata,
                    outcome
                )
                VALUES (
                    %s, %s, %s, 'user', 'flow_package_draft_installed',
                    'flow', %s, 'Synthetic package import audit',
                    '{"extra":{"package_id":"se.test.lifecycle"}}'::jsonb,
                    'success'
                )
                """,
                (ids.audit, ids.tenant, ids.user, ids.flow),
            )
    return ids


def _assert_flow_import_fk_and_index(conn: PsycopgConnection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                constraint_row.confdeltype,
                constraint_row.confupdtype,
                constraint_row.confmatchtype,
                constraint_row.convalidated,
                pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flow_package_imports'
              AND constraint_row.conname =
                  'fk_flow_package_imports_flow_tenant_space'
            """
        )
        constraint = cursor.fetchone()
        assert constraint is not None
        assert constraint[0] == "c"
        assert constraint[1] == "a"
        assert constraint[2] == "s"
        assert constraint[3] is True
        assert (
            "FOREIGN KEY (flow_id, tenant_id, space_id) "
            "REFERENCES flows(id, tenant_id, space_id) ON DELETE CASCADE"
            in constraint[4]
        )

        cursor.execute(
            """
            SELECT count(*)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flow_package_imports'
              AND constraint_row.conname = 'fk_flow_package_imports_flow_id_flows'
            """
        )
        assert cursor.fetchone() == (0,)

        cursor.execute(
            """
            SELECT
                constraint_row.convalidated,
                pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flows'
              AND constraint_row.conname = 'uq_flows_id_tenant_id_space_id'
            """
        )
        unique_constraint = cursor.fetchone()
        assert unique_constraint == (
            True,
            "UNIQUE (id, tenant_id, space_id)",
        )

        cursor.execute(
            """
            SELECT
                index_meta.indisvalid,
                index_meta.indisready,
                pg_get_indexdef(index_meta.indexrelid)
            FROM pg_index AS index_meta
            JOIN pg_class AS index_row
              ON index_row.oid = index_meta.indexrelid
            WHERE index_row.relname = 'uq_flows_id_tenant_id_space_id'
            """
        )
        unique_index = cursor.fetchone()
        assert unique_index is not None
        assert unique_index[0:2] == (True, True)
        assert "(id, tenant_id, space_id)" in unique_index[2]

        cursor.execute(
            """
            SELECT index_meta.indisvalid, index_meta.indisready
            FROM pg_index AS index_meta
            JOIN pg_class AS index_row
              ON index_row.oid = index_meta.indexrelid
            WHERE index_row.relname = 'ix_flow_package_imports_flow_id'
            """
        )
        assert cursor.fetchone() == (True, True)


def _assert_flow_identity_mismatches_are_rejected(
    conn: PsycopgConnection,
    graph: _GraphIds,
) -> None:
    other_space_id = uuid4()
    other_tenant_id = uuid4()
    other_tenant_space_id = uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, %s, %s, %s)
            """,
            (
                other_space_id,
                f"Flow package other space {other_space_id}",
                graph.tenant,
                graph.user,
            ),
        )
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (other_tenant_id, f"flow-package-other-tenant-{other_tenant_id}"),
        )
        cursor.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, %s, %s, NULL)
            """,
            (
                other_tenant_space_id,
                f"Flow package other tenant space {other_tenant_space_id}",
                other_tenant_id,
            ),
        )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as space_error:
        _insert_successful_import(
            conn,
            tenant_id=graph.tenant,
            space_id=other_space_id,
            flow_id=graph.flow,
            created_by_user_id=graph.user,
            package_id="se.test.cross-space",
        )
    assert (
        space_error.value.diag.constraint_name
        == "fk_flow_package_imports_flow_tenant_space"
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as tenant_error:
        _insert_successful_import(
            conn,
            tenant_id=other_tenant_id,
            space_id=other_tenant_space_id,
            flow_id=graph.flow,
            created_by_user_id=graph.user,
            package_id="se.test.cross-tenant",
        )
    assert (
        tenant_error.value.diag.constraint_name
        == "fk_flow_package_imports_flow_tenant_space"
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as move_error:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE flows SET space_id = %s WHERE id = %s",
                (other_space_id, graph.flow),
            )
    assert (
        move_error.value.diag.constraint_name
        == "fk_flow_package_imports_flow_tenant_space"
    )


def _insert_successful_import(
    conn: PsycopgConnection,
    *,
    tenant_id: UUID,
    space_id: UUID,
    flow_id: UUID,
    created_by_user_id: UUID,
    package_id: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO flow_package_imports (
                id,
                tenant_id,
                space_id,
                flow_id,
                created_by_user_id,
                package_id,
                package_version,
                content_checksum,
                source,
                status,
                import_plan_json,
                selected_mappings_json,
                failure_json
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, '1.0.0', %s,
                'file_upload', 'draft_created', '{}'::jsonb, '{}'::jsonb, NULL
            )
            """,
            (
                uuid4(),
                tenant_id,
                space_id,
                flow_id,
                created_by_user_id,
                package_id,
                "b" * 64,
            ),
        )


def _table_exists(conn: PsycopgConnection, table_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
            )
            """,
            (table_name,),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _constraint_exists(
    conn: PsycopgConnection,
    *,
    table_name: str,
    constraint_name: str,
) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint AS constraint_row
                WHERE constraint_row.conrelid = %s::regclass
                  AND constraint_row.conname = %s
            )
            """,
            (table_name, constraint_name),
        )
        row = cursor.fetchone()
    return bool(row and row[0])
