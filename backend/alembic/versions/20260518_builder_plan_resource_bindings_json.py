"""add builder plan resource binding snapshots

Revision ID: 20260518_plan_bindings_json
Revises: 20260518_flow_resource_bindings
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260518_plan_bindings_json"
down_revision = "20260518_flow_resource_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "builder_plans",
        sa.Column(
            "resource_bindings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "Plan-scoped binding snapshot taken at proposal; transferred to "
                "FlowResourceBindings on apply."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("builder_plans", "resource_bindings_json")
