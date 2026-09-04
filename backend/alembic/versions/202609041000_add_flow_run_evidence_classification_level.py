"""add flow run evidence classification level

Revision ID: 202609041000
Revises: 202609031000
Create Date: 2026-09-04 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609041000"
down_revision: str | None = "202609031000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("evidence_classification_level", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_runs", "evidence_classification_level")
