"""file owner identity and audit API-key actor foundation

Adds typed owner identity columns on files and actor_api_key_id on audit_logs.
Flow run principal/idempotency columns are created by the Flow foundation
migration because flow_runs is branch-owned pre-production storage.

Revision ID: 20260411_flow_run_identity
Revises: 202603311430
Create Date: 2026-04-11 13:05:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260411_flow_run_identity"
down_revision = "202603311430"
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
    op.add_column(
        "files",
        sa.Column(
            "owner_type",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column("files", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.add_column("files", sa.Column("owner_api_key_id", sa.UUID(), nullable=True))
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

    op.add_column("audit_logs", sa.Column("actor_api_key_id", sa.UUID(), nullable=True))
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
