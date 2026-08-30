"""add complete Flow run-history retention policies

Revision ID: 202608301525
Revises: 202608281300
Create Date: 2026-08-30 15:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608301525"
down_revision: str | None = "202608281300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODE_CHECK = (
    "flow_run_history_retention_mode IS NULL OR "
    "flow_run_history_retention_mode IN ('preserve','review_required')"
)
_COMPLETE_CHECK = (
    "(flow_run_history_retention_mode IS NULL AND "
    "flow_run_history_retention_days IS NULL) OR "
    "(flow_run_history_retention_mode IS NOT NULL AND "
    "flow_run_history_retention_days IS NOT NULL)"
)


def _add_unvalidated_check(table: str, name: str, condition: str) -> None:
    op.create_check_constraint(
        name,
        table,
        condition,
        postgresql_not_valid=True,
    )


def upgrade() -> None:
    op.alter_column(
        "flows",
        "data_retention_days",
        new_column_name="flow_run_history_retention_days",
    )
    op.execute(
        "ALTER TABLE flows RENAME CONSTRAINT "
        "ck_flows_data_retention_days_range TO "
        "ck_flows_flow_run_history_retention_days_range"
    )

    op.add_column(
        "tenants",
        sa.Column("flow_run_history_retention_mode", sa.String(32), nullable=True),
    )
    op.add_column(
        "spaces",
        sa.Column("flow_run_history_retention_mode", sa.String(32), nullable=True),
    )
    op.add_column(
        "spaces",
        sa.Column("flow_run_history_retention_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "flows",
        sa.Column("flow_run_history_retention_mode", sa.String(32), nullable=True),
    )

    op.execute(
        "UPDATE tenants SET flow_run_history_retention_mode = 'preserve' "
        "WHERE flow_run_history_retention_days IS NOT NULL"
    )
    op.execute(
        "UPDATE spaces SET "
        "flow_run_history_retention_days = data_retention_days, "
        "flow_run_history_retention_mode = 'preserve' "
        "WHERE data_retention_days IS NOT NULL"
    )
    op.execute(
        "UPDATE flows SET flow_run_history_retention_mode = 'preserve' "
        "WHERE flow_run_history_retention_days IS NOT NULL"
    )

    _add_unvalidated_check(
        "tenants",
        "ck_tenants_flow_run_history_retention_complete",
        _COMPLETE_CHECK,
    )
    _add_unvalidated_check(
        "tenants",
        "ck_tenants_flow_run_history_retention_mode",
        _MODE_CHECK,
    )
    _add_unvalidated_check(
        "spaces",
        "ck_spaces_flow_run_history_retention_days_range",
        "flow_run_history_retention_days IS NULL OR "
        "flow_run_history_retention_days BETWEEN 1 AND 2555",
    )
    _add_unvalidated_check(
        "spaces",
        "ck_spaces_flow_run_history_retention_complete",
        _COMPLETE_CHECK,
    )
    _add_unvalidated_check(
        "spaces",
        "ck_spaces_flow_run_history_retention_mode",
        _MODE_CHECK,
    )
    _add_unvalidated_check(
        "flows",
        "ck_flows_flow_run_history_retention_complete",
        _COMPLETE_CHECK,
    )
    _add_unvalidated_check(
        "flows",
        "ck_flows_flow_run_history_retention_mode",
        _MODE_CHECK,
    )
    op.drop_index(
        "ix_flow_runs_terminal_retention_anchor",
        table_name="flow_runs",
    )
    op.create_index(
        "ix_flow_runs_tenant_terminal_retention_anchor",
        "flow_runs",
        [
            "tenant_id",
            sa.literal_column("coalesce(finished_at, created_at)"),
            "id",
        ],
        unique=False,
        postgresql_include=("flow_id",),
        postgresql_where=sa.text("status IN ('completed', 'failed', 'cancelled')"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tenants
                WHERE flow_run_history_retention_mode IS DISTINCT FROM 'preserve'
                  AND flow_run_history_retention_mode IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM flows
                WHERE flow_run_history_retention_mode IS DISTINCT FROM 'preserve'
                  AND flow_run_history_retention_mode IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade Flow retention policies containing review_required';
            END IF;

            IF EXISTS (
                SELECT 1 FROM spaces
                WHERE flow_run_history_retention_mode IS DISTINCT FROM
                    CASE
                        WHEN data_retention_days IS NULL THEN NULL
                        ELSE 'preserve'
                    END
                   OR flow_run_history_retention_days IS DISTINCT FROM data_retention_days
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade a Space Flow policy that differs from conversation retention';
            END IF;
        END
        $$
        """
    )

    op.drop_index(
        "ix_flow_runs_tenant_terminal_retention_anchor",
        table_name="flow_runs",
    )
    op.create_index(
        "ix_flow_runs_terminal_retention_anchor",
        "flow_runs",
        [sa.literal_column("coalesce(finished_at, created_at)"), "id"],
        unique=False,
        postgresql_include=("flow_id",),
        postgresql_where=sa.text("status IN ('completed', 'failed', 'cancelled')"),
    )

    op.drop_constraint(
        "ck_flows_flow_run_history_retention_mode",
        "flows",
        type_="check",
    )
    op.drop_constraint(
        "ck_flows_flow_run_history_retention_complete",
        "flows",
        type_="check",
    )
    op.drop_constraint(
        "ck_spaces_flow_run_history_retention_mode",
        "spaces",
        type_="check",
    )
    op.drop_constraint(
        "ck_spaces_flow_run_history_retention_complete",
        "spaces",
        type_="check",
    )
    op.drop_constraint(
        "ck_spaces_flow_run_history_retention_days_range",
        "spaces",
        type_="check",
    )
    op.drop_constraint(
        "ck_tenants_flow_run_history_retention_mode",
        "tenants",
        type_="check",
    )
    op.drop_constraint(
        "ck_tenants_flow_run_history_retention_complete",
        "tenants",
        type_="check",
    )

    op.drop_column("flows", "flow_run_history_retention_mode")
    op.drop_column("spaces", "flow_run_history_retention_days")
    op.drop_column("spaces", "flow_run_history_retention_mode")
    op.drop_column("tenants", "flow_run_history_retention_mode")

    op.execute(
        "ALTER TABLE flows RENAME CONSTRAINT "
        "ck_flows_flow_run_history_retention_days_range TO "
        "ck_flows_data_retention_days_range"
    )
    op.alter_column(
        "flows",
        "flow_run_history_retention_days",
        new_column_name="data_retention_days",
    )
