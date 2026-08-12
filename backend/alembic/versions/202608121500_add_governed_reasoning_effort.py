"""add governed reasoning effort

Revision ID: 202608121500
Revises: 202608101300
Create Date: 2026-08-12 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608121500"
down_revision: str | None = "202608101300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "governance_policies",
        sa.Column(
            "reasoning_policy_configured",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "governance_policies",
        sa.Column("default_reasoning_effort", sa.String(), nullable=True),
    )
    op.add_column(
        "governance_policies",
        sa.Column(
            "allow_user_reasoning_effort",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("governance_policies", "allow_user_reasoning_effort")
    op.drop_column("governance_policies", "default_reasoning_effort")
    op.drop_column("governance_policies", "reasoning_policy_configured")
