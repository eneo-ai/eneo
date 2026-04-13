"""add flow service-principal foundation

Revision ID: 20260411_flow_service_principal
Revises: 20260411_flow_run_idempotency
Create Date: 2026-04-11 13:40:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260411_flow_service_principal"
down_revision = "20260411_flow_run_idempotency"
branch_labels = None
depends_on = None


def _add_constraint_if_missing(name: str, ddl: str) -> None:
    statement = ddl.strip().rstrip(";")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
            ) THEN
                {statement};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE flow_runs
        ADD COLUMN IF NOT EXISTS principal_type VARCHAR(32) NOT NULL DEFAULT 'user'
        """
    )
    op.execute(
        """
        ALTER TABLE flow_runs
        ADD COLUMN IF NOT EXISTS principal_user_id UUID
        """
    )
    op.execute(
        """
        ALTER TABLE flow_runs
        ADD COLUMN IF NOT EXISTS principal_api_key_id UUID
        """
    )
    op.execute("UPDATE flow_runs SET principal_user_id = user_id WHERE user_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS uq_flow_runs_idempotency_key")
    _add_constraint_if_missing(
        "fk_flow_runs_principal_user_id",
        """
        ALTER TABLE flow_runs
        ADD CONSTRAINT fk_flow_runs_principal_user_id
        FOREIGN KEY (principal_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT
        """,
    )
    _add_constraint_if_missing(
        "fk_flow_runs_principal_api_key_id",
        """
        ALTER TABLE flow_runs
        ADD CONSTRAINT fk_flow_runs_principal_api_key_id
        FOREIGN KEY (principal_api_key_id)
        REFERENCES api_keys_v2(id)
        ON DELETE RESTRICT
        """,
    )
    _add_constraint_if_missing(
        "ck_flow_runs_principal_type",
        """
        ALTER TABLE flow_runs
        ADD CONSTRAINT ck_flow_runs_principal_type
        CHECK (principal_type IN ('user','service_key'))
        """,
    )
    _add_constraint_if_missing(
        "ck_flow_runs_principal_identity",
        """
        ALTER TABLE flow_runs
        ADD CONSTRAINT ck_flow_runs_principal_identity
        CHECK (
            (
                principal_type = 'user'
                AND principal_user_id IS NOT NULL
                AND principal_api_key_id IS NULL
            )
            OR (
                principal_type = 'service_key'
                AND principal_user_id IS NULL
                AND principal_api_key_id IS NOT NULL
            )
        )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_runs_idempotency_user_key
        ON flow_runs (tenant_id, flow_id, principal_user_id, idempotency_key)
        WHERE principal_type = 'user' AND idempotency_key IS NOT NULL
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_runs_idempotency_service_key
        ON flow_runs (tenant_id, flow_id, principal_api_key_id, idempotency_key)
        WHERE principal_type = 'service_key' AND idempotency_key IS NOT NULL
        """,
    )

    op.execute(
        """
        ALTER TABLE files
        ADD COLUMN IF NOT EXISTS owner_type VARCHAR(32) NOT NULL DEFAULT 'user'
        """
    )
    op.execute(
        """
        ALTER TABLE files
        ADD COLUMN IF NOT EXISTS owner_user_id UUID
        """
    )
    op.execute(
        """
        ALTER TABLE files
        ADD COLUMN IF NOT EXISTS owner_api_key_id UUID
        """
    )
    op.execute("UPDATE files SET owner_user_id = user_id WHERE user_id IS NOT NULL")
    op.alter_column("files", "user_id", existing_type=sa.UUID(), nullable=True)
    _add_constraint_if_missing(
        "fk_files_owner_user_id",
        """
        ALTER TABLE files
        ADD CONSTRAINT fk_files_owner_user_id
        FOREIGN KEY (owner_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT
        """,
    )
    _add_constraint_if_missing(
        "fk_files_owner_api_key_id",
        """
        ALTER TABLE files
        ADD CONSTRAINT fk_files_owner_api_key_id
        FOREIGN KEY (owner_api_key_id)
        REFERENCES api_keys_v2(id)
        ON DELETE RESTRICT
        """,
    )
    _add_constraint_if_missing(
        "ck_files_owner_type",
        """
        ALTER TABLE files
        ADD CONSTRAINT ck_files_owner_type
        CHECK (owner_type IN ('user','service_key'))
        """,
    )
    _add_constraint_if_missing(
        "ck_files_owner_identity",
        """
        ALTER TABLE files
        ADD CONSTRAINT ck_files_owner_identity
        CHECK (
            (
                owner_type = 'user'
                AND owner_user_id IS NOT NULL
                AND owner_api_key_id IS NULL
            )
            OR (
                owner_type = 'service_key'
                AND owner_user_id IS NULL
                AND owner_api_key_id IS NOT NULL
            )
        )
        """,
    )

    op.execute(
        """
        ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS actor_api_key_id UUID
        """
    )
    _add_constraint_if_missing(
        "fk_audit_logs_actor_api_key_id",
        """
        ALTER TABLE audit_logs
        ADD CONSTRAINT fk_audit_logs_actor_api_key_id
        FOREIGN KEY (actor_api_key_id)
        REFERENCES api_keys_v2(id)
        ON DELETE SET NULL
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_actor_api_key
        ON audit_logs (tenant_id, actor_api_key_id, timestamp)
        """,
    )


def downgrade() -> None:
    op.drop_index("idx_audit_actor_api_key", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_actor_api_key_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "actor_api_key_id")

    op.drop_constraint("ck_files_owner_identity", "files", type_="check")
    op.drop_constraint("ck_files_owner_type", "files", type_="check")
    op.drop_constraint("fk_files_owner_api_key_id", "files", type_="foreignkey")
    op.drop_constraint("fk_files_owner_user_id", "files", type_="foreignkey")
    op.alter_column("files", "user_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("files", "owner_api_key_id")
    op.drop_column("files", "owner_user_id")
    op.drop_column("files", "owner_type")

    op.drop_index("uq_flow_runs_idempotency_service_key", table_name="flow_runs")
    op.drop_index("uq_flow_runs_idempotency_user_key", table_name="flow_runs")
    op.drop_constraint("ck_flow_runs_principal_identity", "flow_runs", type_="check")
    op.drop_constraint("ck_flow_runs_principal_type", "flow_runs", type_="check")
    op.drop_constraint("fk_flow_runs_principal_api_key_id", "flow_runs", type_="foreignkey")
    op.drop_constraint("fk_flow_runs_principal_user_id", "flow_runs", type_="foreignkey")
    op.create_index(
        "uq_flow_runs_idempotency_key",
        "flow_runs",
        ["tenant_id", "flow_id", "user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_column("flow_runs", "request_fingerprint")
    op.drop_column("flow_runs", "idempotency_key")
    op.drop_column("flow_runs", "principal_api_key_id")
    op.drop_column("flow_runs", "principal_user_id")
    op.drop_column("flow_runs", "principal_type")
