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
    )
    op.create_check_constraint(
        "ck_flow_runs_running_execution_heartbeat",
        "flow_runs",
        "status <> 'running' OR execution_heartbeat_at IS NOT NULL",
        postgresql_not_valid=True,
    )
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(
                "UPDATE flow_runs SET execution_heartbeat_at = updated_at WHERE status = 'running'"
            )
            op.execute(
                "ALTER TABLE flow_runs VALIDATE CONSTRAINT ck_flow_runs_running_execution_heartbeat"
            )
            op.create_index(
                "ix_flow_runs_running_execution_heartbeat",
                "flow_runs",
                ["execution_heartbeat_at", "id"],
                postgresql_include=["tenant_id", "revision"],
                postgresql_where=sa.text("status = 'running'"),
                postgresql_concurrently=True,
            )
            op.drop_index(
                "ix_flow_runs_running_updated_at",
                table_name="flow_runs",
                postgresql_concurrently=True,
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
