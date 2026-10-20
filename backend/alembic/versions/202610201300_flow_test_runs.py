"""flow test runs

A run executes the definition it was started with, kept on the run itself,
so a draft can be tried without publishing: such a test run has no flow
version. Existing runs get their published definition copied over.

Revision ID: 202610201300
Revises: 202610201200
Create Date: 2026-10-20 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202610201300"
down_revision: str | None = "202610201200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("flow_runs", sa.Column("definition", JSONB(), nullable=True))
    op.add_column(
        "flow_runs",
        sa.Column(
            "is_test", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_runs AS r
            SET definition = v.definition
            FROM flow_versions AS v
            WHERE v.flow_id = r.flow_id AND v.version = r.flow_version
            """
        )
    )
    op.alter_column(
        "flow_runs", "flow_version", existing_type=sa.Integer(), nullable=True
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM flow_runs WHERE flow_version IS NULL"))
    op.alter_column(
        "flow_runs", "flow_version", existing_type=sa.Integer(), nullable=False
    )
    op.drop_column("flow_runs", "is_test")
    op.drop_column("flow_runs", "definition")
