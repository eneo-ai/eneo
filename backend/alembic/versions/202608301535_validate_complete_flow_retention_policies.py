"""validate complete Flow run-history retention policies

Revision ID: 202608301535
Revises: 202608301525
Create Date: 2026-08-30 15:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608301535"
down_revision: str | None = "202608301525"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = {
    "tenants": (
        "ck_tenants_flow_run_history_retention_complete",
        "ck_tenants_flow_run_history_retention_mode",
    ),
    "spaces": (
        "ck_spaces_flow_run_history_retention_days_range",
        "ck_spaces_flow_run_history_retention_complete",
        "ck_spaces_flow_run_history_retention_mode",
    ),
    "flows": (
        "ck_flows_flow_run_history_retention_complete",
        "ck_flows_flow_run_history_retention_mode",
    ),
}


def upgrade() -> None:
    for table, constraints in _CONSTRAINTS.items():
        for constraint in constraints:
            op.execute(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{constraint}"')


def downgrade() -> None:
    pass
