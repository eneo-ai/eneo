"""PostgreSQL contract for Flow review-checkpoint actor deletion policy."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607221930_drop_step_deps"
MIGRATION_REVISION = "202607230130_review_actor_delete"

ACTOR_FOREIGN_KEYS = {
    "fk_review_checkpoints_requester_user": ("requester_user_id", "users"),
    "fk_review_checkpoints_requester_service": (
        "requester_service_id",
        "service_principals",
    ),
    "fk_review_checkpoints_decided_by_user": ("decided_by_user_id", "users"),
    "fk_review_checkpoints_decided_by_service": (
        "decided_by_service_id",
        "service_principals",
    ),
}
ACTOR_CHECKS = (
    "ck_flow_run_review_checkpoints_requester_principal",
    "ck_flow_run_review_checkpoints_decider_principal",
)


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
def fresh_chain_db(
    test_settings,
) -> Iterator[tuple[PsycopgConnection, Config]]:
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
    command.upgrade(cfg, PRIOR_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _foreign_key_metadata(
    conn: PsycopgConnection, constraint_name: str
) -> tuple[str, str, str, bool] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                source_attribute.attname,
                target_table.relname,
                constraint_row.confdeltype,
                constraint_row.convalidated
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS source_table
              ON source_table.oid = constraint_row.conrelid
            JOIN pg_class AS target_table
              ON target_table.oid = constraint_row.confrelid
            JOIN pg_attribute AS source_attribute
              ON source_attribute.attrelid = source_table.oid
             AND source_attribute.attnum = constraint_row.conkey[1]
            WHERE source_table.relname = 'flow_run_review_checkpoints'
              AND constraint_row.conname = %s
            """,
            (constraint_name,),
        )
        row = cursor.fetchone()
    return tuple(row) if row is not None else None


def _check_metadata(conn: PsycopgConnection, constraint_name: str) -> tuple[str, bool]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                pg_get_constraintdef(constraint_row.oid),
                constraint_row.convalidated
            FROM pg_constraint AS constraint_row
            WHERE constraint_row.conrelid =
                  'flow_run_review_checkpoints'::regclass
              AND constraint_row.conname = %s
            """,
            (constraint_name,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def _assert_actor_contract(conn: PsycopgConnection, *, user_delete_action: str) -> None:
    for constraint_name, (column_name, target_table) in ACTOR_FOREIGN_KEYS.items():
        expected_action = user_delete_action if target_table == "users" else "r"
        assert _foreign_key_metadata(conn, constraint_name) == (
            column_name,
            target_table,
            expected_action,
            True,
        )

    for constraint_name in ACTOR_CHECKS:
        _, validated = _check_metadata(conn, constraint_name)
        assert validated is True


def _insert_tenant(conn: PsycopgConnection) -> UUID:
    tenant_id = uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (tenant_id, f"review-actor-policy-{tenant_id}"),
        )
    return tenant_id


def _insert_user(conn: PsycopgConnection, tenant_id: UUID) -> UUID:
    user_id = uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (
                id, email, state, tenant_id, quota_limit, used_tokens
            )
            VALUES (%s, %s, 'active', %s, NULL, 0)
            """,
            (user_id, f"{user_id}@example.test", tenant_id),
        )
    return user_id


def _insert_service_principal(conn: PsycopgConnection, tenant_id: UUID) -> UUID:
    service_id = uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO service_principals (
                id, tenant_id, display_name, scope_type, state
            )
            VALUES (%s, %s, %s, 'tenant', 'active')
            """,
            (service_id, tenant_id, f"Review actor {service_id}"),
        )
    return service_id


def _insert_checkpoint(
    conn: PsycopgConnection,
    *,
    tenant_id: UUID,
    requester_type: str,
    requester_user_id: UUID | None = None,
    requester_service_id: UUID | None = None,
    decider_type: str | None = None,
    decider_user_id: UUID | None = None,
    decider_service_id: UUID | None = None,
) -> UUID:
    checkpoint_id = uuid4()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = replica")
            cursor.execute(
                """
                INSERT INTO flow_run_review_checkpoints (
                    id,
                    tenant_id,
                    flow_id,
                    flow_run_id,
                    step_id,
                    step_order,
                    attempt_no,
                    state,
                    revision,
                    schema_version,
                    original_payload_json,
                    current_payload_json,
                    step_label,
                    review_mode,
                    output_type,
                    requester_principal_type,
                    requester_user_id,
                    requester_service_id,
                    decided_by_principal_type,
                    decided_by_user_id,
                    decided_by_service_id
                )
                VALUES (
                    %s, %s, %s, %s, %s, 1, 1, 'resumed', 1, 1,
                    %s, %s, 'Actor deletion policy', 'view', 'json',
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    checkpoint_id,
                    tenant_id,
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    Json({"answer": "original"}),
                    Json({"answer": "current"}),
                    requester_type,
                    requester_user_id,
                    requester_service_id,
                    decider_type,
                    decider_user_id,
                    decider_service_id,
                ),
            )
    finally:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = DEFAULT")
    return checkpoint_id


def _assert_delete_restricted(
    conn: PsycopgConnection,
    *,
    table_name: str,
    actor_id: UUID,
    expected_constraint: str,
) -> None:
    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as exc_info:
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table_name} WHERE id = %s", (actor_id,))
    assert exc_info.value.diag.constraint_name == expected_constraint
    conn.rollback()


def test_upgrade_downgrade_and_replay_restore_exact_mixed_contract(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    _assert_actor_contract(conn, user_delete_action="n")
    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_actor_contract(conn, user_delete_action="r")

    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    _assert_actor_contract(conn, user_delete_action="n")

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_actor_contract(conn, user_delete_action="r")


@pytest.mark.parametrize("drift_kind", ("service_fk_action", "unvalidated_actor_check"))
def test_preflight_rejects_actor_constraint_drift(
    fresh_chain_db: tuple[PsycopgConnection, Config], drift_kind: str
) -> None:
    conn, cfg = fresh_chain_db

    with conn.cursor() as cursor:
        if drift_kind == "service_fk_action":
            cursor.execute(
                """
                ALTER TABLE flow_run_review_checkpoints
                DROP CONSTRAINT fk_review_checkpoints_requester_service
                """
            )
            cursor.execute(
                """
                ALTER TABLE flow_run_review_checkpoints
                ADD CONSTRAINT fk_review_checkpoints_requester_service
                FOREIGN KEY (requester_service_id)
                REFERENCES service_principals (id)
                ON DELETE SET NULL
                """
            )
        else:
            constraint_name = ACTOR_CHECKS[1]
            definition, _ = _check_metadata(conn, constraint_name)
            cursor.execute(
                f"""
                ALTER TABLE flow_run_review_checkpoints
                DROP CONSTRAINT {constraint_name}
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE flow_run_review_checkpoints
                ADD CONSTRAINT {constraint_name} {definition} NOT VALID
                """
            )

    with pytest.raises(Exception, match="Unexpected review-checkpoint actor"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {PRIOR_REVISION}


def test_restricts_requester_and_decider_user_and_service_deletion(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db
    command.upgrade(cfg, MIGRATION_REVISION)

    tenant_id = _insert_tenant(conn)
    requester_user = _insert_user(conn, tenant_id)
    decider_user = _insert_user(conn, tenant_id)
    supporting_user = _insert_user(conn, tenant_id)
    requester_service = _insert_service_principal(conn, tenant_id)
    decider_service = _insert_service_principal(conn, tenant_id)
    supporting_service = _insert_service_principal(conn, tenant_id)

    _insert_checkpoint(
        conn,
        tenant_id=tenant_id,
        requester_type="user",
        requester_user_id=requester_user,
    )
    _insert_checkpoint(
        conn,
        tenant_id=tenant_id,
        requester_type="service_key",
        requester_service_id=supporting_service,
        decider_type="user",
        decider_user_id=decider_user,
    )
    _insert_checkpoint(
        conn,
        tenant_id=tenant_id,
        requester_type="service_key",
        requester_service_id=requester_service,
    )
    _insert_checkpoint(
        conn,
        tenant_id=tenant_id,
        requester_type="user",
        requester_user_id=supporting_user,
        decider_type="service_key",
        decider_service_id=decider_service,
    )

    _assert_delete_restricted(
        conn,
        table_name="users",
        actor_id=requester_user,
        expected_constraint="fk_review_checkpoints_requester_user",
    )
    _assert_delete_restricted(
        conn,
        table_name="users",
        actor_id=decider_user,
        expected_constraint="fk_review_checkpoints_decided_by_user",
    )
    _assert_delete_restricted(
        conn,
        table_name="service_principals",
        actor_id=requester_service,
        expected_constraint="fk_review_checkpoints_requester_service",
    )
    _assert_delete_restricted(
        conn,
        table_name="service_principals",
        actor_id=decider_service,
        expected_constraint="fk_review_checkpoints_decided_by_service",
    )


def test_tenant_delete_cascades_checkpoint_and_actor_rows(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db
    command.upgrade(cfg, MIGRATION_REVISION)

    tenant_id = _insert_tenant(conn)
    requester_user = _insert_user(conn, tenant_id)
    decider_user = _insert_user(conn, tenant_id)
    requester_service = _insert_service_principal(conn, tenant_id)
    decider_service = _insert_service_principal(conn, tenant_id)
    checkpoint_ids = (
        _insert_checkpoint(
            conn,
            tenant_id=tenant_id,
            requester_type="user",
            requester_user_id=requester_user,
            decider_type="service_key",
            decider_service_id=decider_service,
        ),
        _insert_checkpoint(
            conn,
            tenant_id=tenant_id,
            requester_type="service_key",
            requester_service_id=requester_service,
            decider_type="user",
            decider_user_id=decider_user,
        ),
    )

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM flow_run_review_checkpoints
                 WHERE id = ANY(%s)),
                (SELECT count(*) FROM users WHERE id = ANY(%s)),
                (SELECT count(*) FROM service_principals WHERE id = ANY(%s))
            """,
            (
                list(checkpoint_ids),
                [requester_user, decider_user],
                [requester_service, decider_service],
            ),
        )
        assert cursor.fetchone() == (0, 0, 0)
