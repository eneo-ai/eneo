"""Flow run history follows the space's time; remove the Flow modes

The space's time (`spaces.data_retention_days`) caps every flow in it, and a
flow may choose a shorter time. The modes, and the organisation's and the
space's Flow-only times, are removed. Every flow's own time is emptied: an
earlier time was chosen under other rules, so an administrator chooses again.

The downgrade restores the columns and checks, not the values: the
organisation's Flow time, every mode, and every flow time from before the
upgrade are lost. It gives each space's time back to its Flow-only pair and
each flow time chosen since the upgrade the mode `preserve`, the earlier
meaning of a time that only an explicit purge acts on.

Revision ID: 202611231030
Revises: 202611231020
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611231030"
down_revision: str | None = "202611231020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DAYS_RANGE_CHECK = (
    "flow_run_history_retention_days IS NULL OR "
    "(flow_run_history_retention_days BETWEEN 1 AND 2555)"
)
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


def _drop_checks(table: str, *names: str) -> None:
    for name in names:
        op.drop_constraint(name, table, type_="check")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in ("tenants", "spaces"):
        _drop_checks(
            table,
            f"ck_{table}_flow_run_history_retention_mode",
            f"ck_{table}_flow_run_history_retention_complete",
            f"ck_{table}_flow_run_history_retention_days_range",
        )
        op.drop_column(table, "flow_run_history_retention_mode")
        op.drop_column(table, "flow_run_history_retention_days")

    # The completeness check goes first: it refuses a time without a mode.
    _drop_checks(
        "flows",
        "ck_flows_flow_run_history_retention_mode",
        "ck_flows_flow_run_history_retention_complete",
    )
    op.execute(
        "UPDATE flows SET flow_run_history_retention_days = NULL "
        "WHERE flow_run_history_retention_days IS NOT NULL"
    )
    op.drop_column("flows", "flow_run_history_retention_mode")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "tenants",
        sa.Column("flow_run_history_retention_days", sa.Integer(), nullable=True),
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
        "UPDATE spaces SET "
        "flow_run_history_retention_days = data_retention_days, "
        "flow_run_history_retention_mode = 'preserve' "
        "WHERE data_retention_days IS NOT NULL"
    )
    op.execute(
        "UPDATE flows SET flow_run_history_retention_mode = 'preserve' "
        "WHERE flow_run_history_retention_days IS NOT NULL"
    )

    for table in ("tenants", "spaces"):
        op.create_check_constraint(
            f"ck_{table}_flow_run_history_retention_days_range",
            table,
            _DAYS_RANGE_CHECK,
        )
    for table in ("tenants", "spaces", "flows"):
        op.create_check_constraint(
            f"ck_{table}_flow_run_history_retention_complete",
            table,
            _COMPLETE_CHECK,
        )
        op.create_check_constraint(
            f"ck_{table}_flow_run_history_retention_mode", table, _MODE_CHECK
        )
