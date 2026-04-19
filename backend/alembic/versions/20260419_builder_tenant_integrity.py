"""add tenant-consistent builder relationship constraints

Revision ID: 20260419_builder_tenant_guard
Revises: 20260419_builder_send_leases
Create Date: 2026-04-19 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260419_builder_tenant_guard"
down_revision = "20260419_builder_send_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    invalid_plan_link = conn.execute(
        sa.text(
            "SELECT 1 "
            "FROM builder_plans bp "
            "JOIN builder_sessions bs ON bp.session_id = bs.id "
            "WHERE bp.tenant_id <> bs.tenant_id "
            "LIMIT 1"
        )
    ).scalar()
    if invalid_plan_link is not None:
        raise RuntimeError(
            "Cannot apply builder tenant-integrity migration: builder_plans contains cross-tenant session references."
        )

    invalid_session_file_link = conn.execute(
        sa.text(
            "SELECT 1 "
            "FROM builder_session_files bsf "
            "JOIN builder_sessions bs ON bsf.session_id = bs.id "
            "WHERE bsf.tenant_id <> bs.tenant_id "
            "LIMIT 1"
        )
    ).scalar()
    if invalid_session_file_link is not None:
        raise RuntimeError(
            "Cannot apply builder tenant-integrity migration: builder_session_files contains cross-tenant session references."
        )

    invalid_flow_link = conn.execute(
        sa.text(
            "SELECT 1 "
            "FROM builder_sessions bs "
            "JOIN flows f ON bs.flow_id = f.id "
            "WHERE bs.flow_id IS NOT NULL AND bs.tenant_id <> f.tenant_id "
            "LIMIT 1"
        )
    ).scalar()
    if invalid_flow_link is not None:
        raise RuntimeError(
            "Cannot apply builder tenant-integrity migration: builder_sessions contains cross-tenant flow references."
        )

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
