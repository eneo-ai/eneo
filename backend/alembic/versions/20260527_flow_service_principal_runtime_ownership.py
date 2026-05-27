"""key Flow runtime ownership by stable service principals

Revision ID: 20260527_flow_sp_runtime_owner
Revises: 20260527_service_principals
Create Date: 2026-05-27 13:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260527_flow_sp_runtime_owner"
down_revision = "20260527_service_principals"
branch_labels = None
depends_on = None


_FLOW_RUNS = "flow_runs"
_FILES = "files"
_REVIEW_CHECKPOINTS = "flow_run_review_checkpoints"
_RERUN_OPERATIONS = "flow_run_rerun_operations"

_FLOW_RUNS_EXACT_KEY_FK = "fk_flow_runs_principal_api_key_id"
_FILES_EXACT_KEY_FK = "fk_files_owner_api_key_id"
_FLOW_RUNS_PRINCIPAL_CHECK = "ck_flow_runs_principal_identity"
_FILES_OWNER_CHECK = "ck_files_owner_identity"
_REVIEW_REQUESTER_CHECK = "ck_flow_run_review_checkpoints_requester_principal"
_REVIEW_DECIDER_CHECK = "ck_flow_run_review_checkpoints_decider_principal"
_RERUN_USER_ONLY_CHECK = "ck_flow_run_rerun_operations_user_principal"
_RERUN_REQUESTER_CHECK = "ck_flow_run_rerun_operations_requester_principal"

_FLOW_RUNS_SERVICE_IDEMPOTENCY_INDEX = "uq_flow_runs_idempotency_service_key"
_FLOW_RUNS_SERVICE_LIST_INDEX = "ix_flow_runs_service_principal_created_at"
_FILES_SERVICE_OWNER_INDEX = "ix_files_service_owner_created_at"


def _execute(sql: str) -> None:
    op.execute(sa.text(sql))


def _add_columns() -> None:
    op.add_column(
        _FLOW_RUNS,
        sa.Column("principal_service_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        _FLOW_RUNS,
        sa.Column(
            "created_by_api_key_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        _FLOW_RUNS,
        sa.Column("runtime_service_permission", sa.String(length=32), nullable=True),
    )
    op.add_column(
        _FILES,
        sa.Column("owner_service_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        _REVIEW_CHECKPOINTS,
        sa.Column("requester_service_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        _REVIEW_CHECKPOINTS,
        sa.Column(
            "decided_by_service_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        _RERUN_OPERATIONS,
        sa.Column(
            "requested_by_service_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.alter_column(
        _RERUN_OPERATIONS,
        "requested_by_user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def _backfill_service_ownership() -> None:
    _execute(
        """
        UPDATE flow_runs AS run
        SET
            principal_service_id = api_key.service_principal_id,
            created_by_api_key_id = api_key.id,
            runtime_service_permission = api_key.permission
        FROM api_keys_v2 AS api_key
        WHERE run.principal_type = 'service_key'
          AND run.principal_api_key_id = api_key.id
        """
    )
    _execute(
        """
        UPDATE files AS file
        SET owner_service_id = api_key.service_principal_id
        FROM api_keys_v2 AS api_key
        WHERE file.owner_type = 'service_key'
          AND file.owner_api_key_id = api_key.id
        """
    )
    _execute(
        """
        UPDATE flow_run_review_checkpoints AS checkpoint
        SET requester_service_id = run.principal_service_id
        FROM flow_runs AS run
        WHERE checkpoint.flow_run_id = run.id
          AND checkpoint.tenant_id = run.tenant_id
          AND checkpoint.requester_principal_type = 'service_key'
        """
    )
    _execute(
        """
        UPDATE flow_run_review_checkpoints AS checkpoint
        SET decided_by_service_id = run.principal_service_id
        FROM flow_runs AS run
        WHERE checkpoint.flow_run_id = run.id
          AND checkpoint.tenant_id = run.tenant_id
          AND checkpoint.decided_by_principal_type = 'service_key'
        """
    )


def _assert_backfill_safe() -> None:
    _execute(
        """
        DO $$
        DECLARE
            service_runs_missing_exact_key integer;
            service_runs_missing_principal integer;
            service_run_tenant_mismatches integer;
            service_files_missing_exact_key integer;
            service_files_missing_principal integer;
            service_file_tenant_mismatches integer;
            requester_misses integer;
            decider_misses integer;
            service_reruns integer;
            idempotency_collisions integer;
        BEGIN
            SELECT count(*)
            INTO service_runs_missing_exact_key
            FROM flow_runs AS run
            LEFT JOIN api_keys_v2 AS api_key
              ON api_key.id = run.principal_api_key_id
            WHERE run.principal_type = 'service_key'
              AND api_key.id IS NULL;

            IF service_runs_missing_exact_key > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key flow_runs rows reference missing exact API-key rows.',
                    service_runs_missing_exact_key;
            END IF;

            SELECT count(*)
            INTO service_runs_missing_principal
            FROM flow_runs AS run
            WHERE run.principal_type = 'service_key'
              AND (
                    run.principal_service_id IS NULL
                 OR run.created_by_api_key_id IS NULL
                 OR run.runtime_service_permission NOT IN ('read','write','admin')
              );

            IF service_runs_missing_principal > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key flow_runs rows could not be backfilled.',
                    service_runs_missing_principal;
            END IF;

            SELECT count(*)
            INTO service_run_tenant_mismatches
            FROM flow_runs AS run
            JOIN service_principals AS principal
              ON principal.id = run.principal_service_id
            WHERE run.principal_type = 'service_key'
              AND principal.tenant_id <> run.tenant_id;

            IF service_run_tenant_mismatches > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key flow_runs rows link to a principal in another tenant.',
                    service_run_tenant_mismatches;
            END IF;

            SELECT count(*)
            INTO service_files_missing_exact_key
            FROM files AS file
            LEFT JOIN api_keys_v2 AS api_key
              ON api_key.id = file.owner_api_key_id
            WHERE file.owner_type = 'service_key'
              AND api_key.id IS NULL;

            IF service_files_missing_exact_key > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key files rows reference missing exact API-key rows.',
                    service_files_missing_exact_key;
            END IF;

            SELECT count(*)
            INTO service_files_missing_principal
            FROM files AS file
            WHERE file.owner_type = 'service_key'
              AND file.owner_service_id IS NULL;

            IF service_files_missing_principal > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key files rows could not be backfilled.',
                    service_files_missing_principal;
            END IF;

            SELECT count(*)
            INTO service_file_tenant_mismatches
            FROM files AS file
            JOIN service_principals AS principal
              ON principal.id = file.owner_service_id
            WHERE file.owner_type = 'service_key'
              AND principal.tenant_id <> file.tenant_id;

            IF service_file_tenant_mismatches > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-key files rows link to a principal in another tenant.',
                    service_file_tenant_mismatches;
            END IF;

            SELECT count(*)
            INTO requester_misses
            FROM flow_run_review_checkpoints
            WHERE requester_principal_type = 'service_key'
              AND requester_service_id IS NULL;

            IF requester_misses > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % review checkpoint requesters could not be mapped to service principals.',
                    requester_misses;
            END IF;

            SELECT count(*)
            INTO decider_misses
            FROM flow_run_review_checkpoints
            WHERE decided_by_principal_type = 'service_key'
              AND decided_by_service_id IS NULL;

            IF decider_misses > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % review checkpoint deciders could not be mapped to service principals.',
                    decider_misses;
            END IF;

            SELECT count(*)
            INTO service_reruns
            FROM flow_run_rerun_operations
            WHERE requested_by_principal_type <> 'user';

            IF service_reruns > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % pre-existing non-user rerun operations need explicit operator mapping.',
                    service_reruns;
            END IF;

            SELECT count(*)
            INTO idempotency_collisions
            FROM (
                SELECT
                    run.tenant_id,
                    run.flow_id,
                    run.principal_service_id,
                    run.idempotency_key
                FROM flow_runs AS run
                WHERE run.principal_type = 'service_key'
                  AND run.idempotency_key IS NOT NULL
                GROUP BY
                    run.tenant_id,
                    run.flow_id,
                    run.principal_service_id,
                    run.idempotency_key
                HAVING count(*) > 1
            ) AS collisions;

            IF idempotency_collisions > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate Flow service-principal ownership: % service-principal idempotency key collisions found.',
                    idempotency_collisions;
            END IF;
        END $$;
        """
    )


def _add_not_valid_fk(
    table: str, name: str, column: str, target: str, ondelete: str
) -> None:
    op.create_foreign_key(
        name,
        table,
        target,
        [column],
        ["id"],
        ondelete=ondelete,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _replace_constraints() -> None:
    _execute(
        """
        ALTER TABLE flow_runs
        ADD CONSTRAINT ck_flow_runs_principal_identity_service_principal
        CHECK (
            (
                principal_type = 'user'
                AND principal_user_id IS NOT NULL
                AND principal_service_id IS NULL
                AND runtime_service_permission IS NULL
            )
            OR (
                principal_type = 'service_key'
                AND principal_user_id IS NULL
                AND principal_service_id IS NOT NULL
                AND runtime_service_permission IN ('read','write','admin')
            )
        )
        NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE flow_runs VALIDATE CONSTRAINT "
        "ck_flow_runs_principal_identity_service_principal"
    )
    _execute(
        """
        ALTER TABLE files
        ADD CONSTRAINT ck_files_owner_identity_service_principal
        CHECK (
            (
                owner_type = 'user'
                AND owner_user_id IS NOT NULL
                AND owner_service_id IS NULL
            )
            OR (
                owner_type = 'service_key'
                AND owner_user_id IS NULL
                AND owner_service_id IS NOT NULL
            )
        )
        NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE files VALIDATE CONSTRAINT "
        "ck_files_owner_identity_service_principal"
    )
    _execute(
        """
        ALTER TABLE flow_run_review_checkpoints
        ADD CONSTRAINT ck_review_checkpoints_requester_service_principal
        CHECK (
            (
                requester_principal_type = 'user'
                AND requester_user_id IS NOT NULL
                AND requester_service_id IS NULL
            )
            OR (
                requester_principal_type = 'service_key'
                AND requester_user_id IS NULL
                AND requester_service_id IS NOT NULL
            )
        )
        NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE flow_run_review_checkpoints VALIDATE CONSTRAINT "
        "ck_review_checkpoints_requester_service_principal"
    )
    _execute(
        """
        ALTER TABLE flow_run_review_checkpoints
        ADD CONSTRAINT ck_review_checkpoints_decider_service_principal
        CHECK (
            decided_by_principal_type IS NULL
            OR (
                decided_by_principal_type = 'user'
                AND decided_by_user_id IS NOT NULL
                AND decided_by_service_id IS NULL
            )
            OR (
                decided_by_principal_type = 'service_key'
                AND decided_by_user_id IS NULL
                AND decided_by_service_id IS NOT NULL
            )
        )
        NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE flow_run_review_checkpoints VALIDATE CONSTRAINT "
        "ck_review_checkpoints_decider_service_principal"
    )
    _execute(
        f"""
        ALTER TABLE flow_run_rerun_operations
        ADD CONSTRAINT {_RERUN_REQUESTER_CHECK}
        CHECK (
            (
                requested_by_principal_type = 'user'
                AND requested_by_user_id IS NOT NULL
                AND requested_by_service_id IS NULL
            )
            OR (
                requested_by_principal_type = 'service_key'
                AND requested_by_user_id IS NULL
                AND requested_by_service_id IS NOT NULL
            )
        )
        NOT VALID
        """
    )
    op.execute(
        f"ALTER TABLE flow_run_rerun_operations VALIDATE CONSTRAINT {_RERUN_REQUESTER_CHECK}"
    )

    _add_not_valid_fk(
        _FLOW_RUNS,
        "fk_flow_runs_principal_service_id",
        "principal_service_id",
        "service_principals",
        "RESTRICT",
    )
    _add_not_valid_fk(
        _FLOW_RUNS,
        "fk_flow_runs_created_by_api_key_id",
        "created_by_api_key_id",
        "api_keys_v2",
        "SET NULL",
    )
    _add_not_valid_fk(
        _FILES,
        "fk_files_owner_service_id",
        "owner_service_id",
        "service_principals",
        "RESTRICT",
    )
    _add_not_valid_fk(
        _REVIEW_CHECKPOINTS,
        "fk_review_checkpoints_requester_service",
        "requester_service_id",
        "service_principals",
        "RESTRICT",
    )
    _add_not_valid_fk(
        _REVIEW_CHECKPOINTS,
        "fk_review_checkpoints_decided_by_service",
        "decided_by_service_id",
        "service_principals",
        "RESTRICT",
    )
    _add_not_valid_fk(
        _RERUN_OPERATIONS,
        "fk_rerun_operations_requested_by_service",
        "requested_by_service_id",
        "service_principals",
        "RESTRICT",
    )

    op.drop_constraint(_FLOW_RUNS_PRINCIPAL_CHECK, _FLOW_RUNS, type_="check")
    op.drop_constraint(_FILES_OWNER_CHECK, _FILES, type_="check")
    op.drop_constraint(_REVIEW_REQUESTER_CHECK, _REVIEW_CHECKPOINTS, type_="check")
    op.drop_constraint(_REVIEW_DECIDER_CHECK, _REVIEW_CHECKPOINTS, type_="check")
    op.drop_constraint(_RERUN_USER_ONLY_CHECK, _RERUN_OPERATIONS, type_="check")
    _execute(
        """
        ALTER TABLE flow_runs
        RENAME CONSTRAINT ck_flow_runs_principal_identity_service_principal
        TO ck_flow_runs_principal_identity
        """
    )
    _execute(
        """
        ALTER TABLE files
        RENAME CONSTRAINT ck_files_owner_identity_service_principal
        TO ck_files_owner_identity
        """
    )
    _execute(
        """
        ALTER TABLE flow_run_review_checkpoints
        RENAME CONSTRAINT ck_review_checkpoints_requester_service_principal
        TO ck_flow_run_review_checkpoints_requester_principal
        """
    )
    _execute(
        """
        ALTER TABLE flow_run_review_checkpoints
        RENAME CONSTRAINT ck_review_checkpoints_decider_service_principal
        TO ck_flow_run_review_checkpoints_decider_principal
        """
    )


def _replace_indexes() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_FLOW_RUNS_SERVICE_IDEMPOTENCY_INDEX}"
        )
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY {_FLOW_RUNS_SERVICE_IDEMPOTENCY_INDEX}
            ON flow_runs (tenant_id, flow_id, principal_service_id, idempotency_key)
            WHERE principal_type = 'service_key' AND idempotency_key IS NOT NULL
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_FLOW_RUNS_SERVICE_LIST_INDEX}
            ON flow_runs (tenant_id, principal_service_id, created_at DESC)
            WHERE principal_type = 'service_key'
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_FILES_SERVICE_OWNER_INDEX}
            ON files (tenant_id, owner_service_id, created_at)
            WHERE owner_type = 'service_key'
            """
        )


def _drop_exact_owner_columns() -> None:
    op.drop_constraint(_FLOW_RUNS_EXACT_KEY_FK, _FLOW_RUNS, type_="foreignkey")
    op.drop_constraint(_FILES_EXACT_KEY_FK, _FILES, type_="foreignkey")
    op.drop_column(_FLOW_RUNS, "principal_api_key_id")
    op.drop_column(_FILES, "owner_api_key_id")


def upgrade() -> None:
    _add_columns()
    _backfill_service_ownership()
    _assert_backfill_safe()
    _replace_constraints()
    _replace_indexes()
    _drop_exact_owner_columns()


def _assert_downgrade_safe() -> None:
    _execute(
        """
        DO $$
        DECLARE
            service_runs integer;
            service_files integer;
            service_review_actors integer;
            service_reruns integer;
        BEGIN
            SELECT count(*) INTO service_runs
            FROM flow_runs
            WHERE principal_type = 'service_key';

            SELECT count(*) INTO service_files
            FROM files
            WHERE owner_type = 'service_key';

            SELECT count(*) INTO service_review_actors
            FROM flow_run_review_checkpoints
            WHERE requester_principal_type = 'service_key'
               OR decided_by_principal_type = 'service_key';

            SELECT count(*) INTO service_reruns
            FROM flow_run_rerun_operations
            WHERE requested_by_principal_type = 'service_key';

            IF service_runs + service_files + service_review_actors + service_reruns > 0 THEN
                RAISE EXCEPTION
                    'Downgrade from service-principal Flow ownership is unsupported while service-principal Flow data exists.';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    _assert_downgrade_safe()

    op.add_column(
        _FLOW_RUNS,
        sa.Column("principal_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        _FILES,
        sa.Column("owner_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column(
        _RERUN_OPERATIONS,
        "requested_by_user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.drop_constraint(_FLOW_RUNS_PRINCIPAL_CHECK, _FLOW_RUNS, type_="check")
    op.drop_constraint(_FILES_OWNER_CHECK, _FILES, type_="check")
    op.drop_constraint(_REVIEW_REQUESTER_CHECK, _REVIEW_CHECKPOINTS, type_="check")
    op.drop_constraint(_REVIEW_DECIDER_CHECK, _REVIEW_CHECKPOINTS, type_="check")
    op.drop_constraint(_RERUN_REQUESTER_CHECK, _RERUN_OPERATIONS, type_="check")

    op.create_check_constraint(
        _FLOW_RUNS_PRINCIPAL_CHECK,
        _FLOW_RUNS,
        "("
        "(principal_type = 'user' "
        "AND principal_user_id IS NOT NULL "
        "AND principal_api_key_id IS NULL) "
        "OR "
        "(principal_type = 'service_key' "
        "AND principal_user_id IS NULL "
        "AND principal_api_key_id IS NOT NULL)"
        ")",
    )
    op.create_check_constraint(
        _FILES_OWNER_CHECK,
        _FILES,
        "("
        "(owner_type = 'user' "
        "AND owner_user_id IS NOT NULL "
        "AND owner_api_key_id IS NULL) "
        "OR "
        "(owner_type = 'service_key' "
        "AND owner_user_id IS NULL "
        "AND owner_api_key_id IS NOT NULL)"
        ")",
    )
    op.create_check_constraint(
        _REVIEW_REQUESTER_CHECK,
        _REVIEW_CHECKPOINTS,
        "requester_principal_type IN ('user','service_key')",
    )
    op.create_check_constraint(
        _REVIEW_DECIDER_CHECK,
        _REVIEW_CHECKPOINTS,
        "decided_by_principal_type IS NULL OR decided_by_principal_type IN ('user','service_key')",
    )
    op.create_check_constraint(
        _RERUN_USER_ONLY_CHECK,
        _RERUN_OPERATIONS,
        "requested_by_principal_type = 'user'",
    )

    op.create_foreign_key(
        _FLOW_RUNS_EXACT_KEY_FK,
        _FLOW_RUNS,
        "api_keys_v2",
        ["principal_api_key_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        _FILES_EXACT_KEY_FK,
        _FILES,
        "api_keys_v2",
        ["owner_api_key_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_flow_runs_principal_service_id", _FLOW_RUNS, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_flow_runs_created_by_api_key_id", _FLOW_RUNS, type_="foreignkey"
    )
    op.drop_constraint("fk_files_owner_service_id", _FILES, type_="foreignkey")
    op.drop_constraint(
        "fk_review_checkpoints_requester_service",
        _REVIEW_CHECKPOINTS,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_review_checkpoints_decided_by_service",
        _REVIEW_CHECKPOINTS,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_rerun_operations_requested_by_service",
        _RERUN_OPERATIONS,
        type_="foreignkey",
    )

    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_FLOW_RUNS_SERVICE_IDEMPOTENCY_INDEX}"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_FLOW_RUNS_SERVICE_LIST_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_FILES_SERVICE_OWNER_INDEX}")
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY {_FLOW_RUNS_SERVICE_IDEMPOTENCY_INDEX}
            ON flow_runs (tenant_id, flow_id, principal_api_key_id, idempotency_key)
            WHERE principal_type = 'service_key' AND idempotency_key IS NOT NULL
            """
        )

    op.drop_column(_FLOW_RUNS, "principal_service_id")
    op.drop_column(_FLOW_RUNS, "created_by_api_key_id")
    op.drop_column(_FLOW_RUNS, "runtime_service_permission")
    op.drop_column(_FILES, "owner_service_id")
    op.drop_column(_REVIEW_CHECKPOINTS, "requester_service_id")
    op.drop_column(_REVIEW_CHECKPOINTS, "decided_by_service_id")
    op.drop_column(_RERUN_OPERATIONS, "requested_by_service_id")
