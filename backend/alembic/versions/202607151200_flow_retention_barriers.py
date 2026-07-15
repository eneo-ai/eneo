"""Add organization and classification Flow retention barriers.

Revision ID: 202607151200_flow_retention_barriers
Revises: 202607131200_flow_retention
Create Date: 2026-07-15 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202607151200_flow_retention_barriers"
down_revision = "202607131200_flow_retention"
branch_labels = None
depends_on = None

_TENANTS_TABLE = "tenants"
_CLASSIFICATION_POLICY_TABLE = "flow_classification_retention_policies"
_TENANT_MINIMUM_COLUMN = "flow_run_history_minimum_retention_days"
_TENANT_NO_PURGE_COLUMN = "flow_run_history_no_purge"
_CLASSIFICATION_MINIMUM_COLUMN = "minimum_retention_days"
_CLASSIFICATION_NO_PURGE_COLUMN = "no_purge"
_TENANT_MINIMUM_CHECK = "ck_tenants_flow_run_history_minimum_retention_days_range"
_CLASSIFICATION_DAYS_CHECK = "ck_flow_classification_retention_policy_days_range"
_CLASSIFICATION_MINIMUM_CHECK = (
    "ck_flow_classification_retention_policy_minimum_days_range"
)
_CLASSIFICATION_HAS_VALUE_CHECK = "ck_flow_classification_retention_policy_has_value"
_TENANT_MINIMUM_CHECK_SQL = (
    f"{_TENANT_MINIMUM_COLUMN} IS NULL OR "
    f"({_TENANT_MINIMUM_COLUMN} >= 1 AND {_TENANT_MINIMUM_COLUMN} <= 2555)"
)
_CLASSIFICATION_DAYS_CHECK_SQL = (
    "data_retention_days IS NULL OR "
    "(data_retention_days >= 1 AND data_retention_days <= 2555)"
)
_CLASSIFICATION_PRIOR_DAYS_CHECK_SQL = (
    "data_retention_days >= 1 AND data_retention_days <= 2555"
)
_CLASSIFICATION_MINIMUM_CHECK_SQL = (
    f"{_CLASSIFICATION_MINIMUM_COLUMN} IS NULL OR "
    f"({_CLASSIFICATION_MINIMUM_COLUMN} >= 1 AND "
    f"{_CLASSIFICATION_MINIMUM_COLUMN} <= 2555)"
)
_CLASSIFICATION_HAS_VALUE_CHECK_SQL = (
    "data_retention_days IS NOT NULL OR minimum_retention_days IS NOT NULL OR no_purge"
)


def _add_validated_check(
    *,
    constraint_name: str,
    table_name: str,
    condition: str,
) -> None:
    op.create_check_constraint(
        constraint_name,
        table_name,
        condition,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table_name} VALIDATE CONSTRAINT {constraint_name}")


def upgrade() -> None:
    # This required revision id exceeds Alembic's historical VARCHAR(32). Alembic
    # writes the new id only after upgrade() returns, so the capacity change must
    # happen inside this revision and remain safe across downgrade.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.add_column(
        _TENANTS_TABLE,
        sa.Column(_TENANT_MINIMUM_COLUMN, sa.Integer(), nullable=True),
    )
    op.add_column(
        _TENANTS_TABLE,
        sa.Column(
            _TENANT_NO_PURGE_COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_validated_check(
        constraint_name=_TENANT_MINIMUM_CHECK,
        table_name=_TENANTS_TABLE,
        condition=_TENANT_MINIMUM_CHECK_SQL,
    )

    op.alter_column(
        _CLASSIFICATION_POLICY_TABLE,
        "data_retention_days",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        _CLASSIFICATION_POLICY_TABLE,
        sa.Column(_CLASSIFICATION_MINIMUM_COLUMN, sa.Integer(), nullable=True),
    )
    op.add_column(
        _CLASSIFICATION_POLICY_TABLE,
        sa.Column(
            _CLASSIFICATION_NO_PURGE_COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.drop_constraint(
        _CLASSIFICATION_DAYS_CHECK,
        _CLASSIFICATION_POLICY_TABLE,
        type_="check",
    )
    _add_validated_check(
        constraint_name=_CLASSIFICATION_DAYS_CHECK,
        table_name=_CLASSIFICATION_POLICY_TABLE,
        condition=_CLASSIFICATION_DAYS_CHECK_SQL,
    )
    _add_validated_check(
        constraint_name=_CLASSIFICATION_MINIMUM_CHECK,
        table_name=_CLASSIFICATION_POLICY_TABLE,
        condition=_CLASSIFICATION_MINIMUM_CHECK_SQL,
    )
    _add_validated_check(
        constraint_name=_CLASSIFICATION_HAS_VALUE_CHECK,
        table_name=_CLASSIFICATION_POLICY_TABLE,
        condition=_CLASSIFICATION_HAS_VALUE_CHECK_SQL,
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM {_TENANTS_TABLE}
                WHERE {_TENANT_MINIMUM_COLUMN} IS NOT NULL
                   OR {_TENANT_NO_PURGE_COLUMN}
            ) OR EXISTS (
                SELECT 1
                FROM {_CLASSIFICATION_POLICY_TABLE}
                WHERE data_retention_days IS NULL
                   OR {_CLASSIFICATION_MINIMUM_COLUMN} IS NOT NULL
                   OR {_CLASSIFICATION_NO_PURGE_COLUMN}
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade Flow retention barriers while barrier data exists';
            END IF;
        END
        $$
        """
    )

    op.drop_constraint(
        _CLASSIFICATION_HAS_VALUE_CHECK,
        _CLASSIFICATION_POLICY_TABLE,
        type_="check",
    )
    op.drop_constraint(
        _CLASSIFICATION_MINIMUM_CHECK,
        _CLASSIFICATION_POLICY_TABLE,
        type_="check",
    )
    op.drop_constraint(
        _CLASSIFICATION_DAYS_CHECK,
        _CLASSIFICATION_POLICY_TABLE,
        type_="check",
    )
    op.alter_column(
        _CLASSIFICATION_POLICY_TABLE,
        "data_retention_days",
        existing_type=sa.Integer(),
        nullable=False,
    )
    _add_validated_check(
        constraint_name=_CLASSIFICATION_DAYS_CHECK,
        table_name=_CLASSIFICATION_POLICY_TABLE,
        condition=_CLASSIFICATION_PRIOR_DAYS_CHECK_SQL,
    )
    op.drop_column(_CLASSIFICATION_POLICY_TABLE, _CLASSIFICATION_NO_PURGE_COLUMN)
    op.drop_column(_CLASSIFICATION_POLICY_TABLE, _CLASSIFICATION_MINIMUM_COLUMN)

    op.drop_constraint(_TENANT_MINIMUM_CHECK, _TENANTS_TABLE, type_="check")
    op.drop_column(_TENANTS_TABLE, _TENANT_NO_PURGE_COLUMN)
    op.drop_column(_TENANTS_TABLE, _TENANT_MINIMUM_COLUMN)
