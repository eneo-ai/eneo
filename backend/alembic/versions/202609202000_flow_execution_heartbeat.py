"""Fence execution ownership with a renewable heartbeat.

Revision ID: 202609202000
Revises: 202609201000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609202000"
down_revision = "202609201000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_runs",
        sa.Column("execution_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'flow_runs'::regclass
                  AND conname = 'ck_flow_runs_running_execution_heartbeat'
            ) THEN
                ALTER TABLE flow_runs
                    ADD CONSTRAINT ck_flow_runs_running_execution_heartbeat
                    CHECK (status <> 'running' OR execution_heartbeat_at IS NOT NULL)
                    NOT VALID;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_index
                WHERE indexrelid = to_regclass('ix_flow_runs_running_execution_heartbeat')
                  AND NOT indisvalid
            ) THEN
                DROP INDEX ix_flow_runs_running_execution_heartbeat;
            END IF;
        END $$
        """
    )
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(
                "UPDATE flow_runs SET execution_heartbeat_at = updated_at "
                "WHERE status = 'running' AND execution_heartbeat_at IS NULL"
            )
            op.execute(
                """
                DO $$ BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'flow_runs'::regclass
                          AND conname = 'ck_flow_runs_running_execution_heartbeat'
                          AND NOT convalidated
                    ) THEN
                        ALTER TABLE flow_runs
                            VALIDATE CONSTRAINT ck_flow_runs_running_execution_heartbeat;
                    END IF;
                END $$
                """
            )
            op.create_index(
                "ix_flow_runs_running_execution_heartbeat",
                "flow_runs",
                ["execution_heartbeat_at", "id"],
                postgresql_include=["tenant_id", "revision"],
                if_not_exists=True,
                postgresql_where=sa.text("status = 'running'"),
                postgresql_concurrently=True,
            )
            op.drop_index(
                "ix_flow_runs_running_updated_at",
                table_name="flow_runs",
                postgresql_concurrently=True,
                if_exists=True,
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.create_index(
                "ix_flow_runs_running_updated_at",
                "flow_runs",
                ["status", "updated_at"],
                postgresql_where=sa.text("status = 'running'"),
                postgresql_concurrently=True,
            )
            op.drop_index(
                "ix_flow_runs_running_execution_heartbeat",
                table_name="flow_runs",
                postgresql_concurrently=True,
            )
        finally:
            op.execute("RESET lock_timeout")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(
        "ck_flow_runs_running_execution_heartbeat", "flow_runs", type_="check"
    )
    op.drop_column("flow_runs", "execution_heartbeat_at")
