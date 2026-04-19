"""add tenant-consistent builder relationship constraints

Revision ID: 20260419_builder_tenant_guard
Revises: 20260419_builder_send_leases
Create Date: 2026-04-19 00:00:00.000000
"""

from alembic import op

revision = "20260419_builder_tenant_guard"
down_revision = "20260419_builder_send_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_builder_sessions_id_tenant_id",
        "builder_sessions",
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_builder_sessions_flow_tenant",
        "builder_sessions",
        "flows",
        ["flow_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_builder_plans_id_tenant_id",
        "builder_plans",
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_builder_plans_session_tenant",
        "builder_plans",
        "builder_sessions",
        ["session_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_builder_session_files_session_tenant",
        "builder_session_files",
        "builder_sessions",
        ["session_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_builder_session_files_session_tenant",
        "builder_session_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_builder_plans_session_tenant",
        "builder_plans",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_builder_sessions_flow_tenant",
        "builder_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_builder_plans_id_tenant_id",
        "builder_plans",
        type_="unique",
    )
    op.drop_constraint(
        "uq_builder_sessions_id_tenant_id",
        "builder_sessions",
        type_="unique",
    )
