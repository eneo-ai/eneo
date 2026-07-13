"""Add tenant-admin Flow retention policy inputs.

Revision ID: 202607131200_flow_retention
Revises: 202607111200_file_tenant_fks
Create Date: 2026-07-13 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202607131200_flow_retention"
down_revision = "202607111200_file_tenant_fks"
branch_labels = None
depends_on = None

_TENANTS_TABLE = "tenants"
_POLICY_COLUMNS = (
    "flow_run_history_retention_days",
    "flow_runtime_upload_abandonment_days",
)
_CONSTRAINTS = (
    (
        "ck_tenants_flow_run_history_retention_days_range",
        "flow_run_history_retention_days IS NULL OR "
        "(flow_run_history_retention_days >= 1 AND "
        "flow_run_history_retention_days <= 2555)",
    ),
    (
        "ck_tenants_flow_runtime_upload_abandonment_days_range",
        "flow_runtime_upload_abandonment_days IS NULL OR "
        "(flow_runtime_upload_abandonment_days >= 1 AND "
        "flow_runtime_upload_abandonment_days <= 2555)",
    ),
)


def upgrade() -> None:
    for column_name in _POLICY_COLUMNS:
        op.add_column(
            _TENANTS_TABLE,
            sa.Column(column_name, sa.Integer(), nullable=True),
        )

    for constraint_name, constraint_sql in _CONSTRAINTS:
        op.create_check_constraint(
            constraint_name,
            _TENANTS_TABLE,
            constraint_sql,
            postgresql_not_valid=True,
        )
        op.execute(
            f"ALTER TABLE {_TENANTS_TABLE} VALIDATE CONSTRAINT {constraint_name}"
        )


def downgrade() -> None:
    for constraint_name, _constraint_sql in reversed(_CONSTRAINTS):
        op.drop_constraint(constraint_name, _TENANTS_TABLE, type_="check")
    for column_name in reversed(_POLICY_COLUMNS):
        op.drop_column(_TENANTS_TABLE, column_name)
