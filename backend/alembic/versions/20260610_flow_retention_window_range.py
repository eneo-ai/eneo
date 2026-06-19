"""bound Flow data retention window

Revision ID: 20260610_flow_retention_range
Revises: 20260608_rerun_input_flag
Create Date: 2026-06-10 20:58:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260610_flow_retention_range"
down_revision = "20260608_rerun_input_flag"
branch_labels = None
depends_on = None

_FLOWS_TABLE = "flows"
_CONSTRAINT_NAME = "ck_flows_data_retention_days_range"
_MIN_RETENTION_DAYS = 1
_MAX_RETENTION_DAYS = 2555
_CONSTRAINT_SQL = (
    "data_retention_days IS NULL OR "
    "(data_retention_days >= 1 AND data_retention_days <= 2555)"
)


def _invalid_flow_retention_count() -> int:
    result = op.get_bind().execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM {_FLOWS_TABLE}
            WHERE data_retention_days IS NOT NULL
              AND (
                data_retention_days < :min_retention_days
                OR data_retention_days > :max_retention_days
              )
            """
        ),
        {
            "min_retention_days": _MIN_RETENTION_DAYS,
            "max_retention_days": _MAX_RETENTION_DAYS,
        },
    )
    return int(result.scalar_one())


def _invalid_flow_retention_samples() -> list[str]:
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT id::text, data_retention_days
            FROM {_FLOWS_TABLE}
            WHERE data_retention_days IS NOT NULL
              AND (
                data_retention_days < :min_retention_days
                OR data_retention_days > :max_retention_days
              )
            ORDER BY created_at, id
            LIMIT 5
            """
        ),
        {
            "min_retention_days": _MIN_RETENTION_DAYS,
            "max_retention_days": _MAX_RETENTION_DAYS,
        },
    )
    return [f"id={row[0]} data_retention_days={row[1]}" for row in rows]


def upgrade() -> None:
    invalid_count = _invalid_flow_retention_count()
    if invalid_count > 0:
        samples = "; ".join(_invalid_flow_retention_samples())
        raise RuntimeError(
            f"Cannot add {_CONSTRAINT_NAME}: {invalid_count} flows rows have "
            f"data_retention_days outside {_MIN_RETENTION_DAYS}-"
            f"{_MAX_RETENTION_DAYS}. Sample flows: {samples}. Repair the "
            "invalid retention policy values, then rerun the upgrade."
        )

    op.create_check_constraint(
        _CONSTRAINT_NAME,
        _FLOWS_TABLE,
        _CONSTRAINT_SQL,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {_FLOWS_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT_NAME}")


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _FLOWS_TABLE, type_="check")
