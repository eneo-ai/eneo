"""Drop duplicate Flow step result tool-call metadata.

Revision ID: 20260502_drop_result_tool_calls
Revises: 20260502_flow_audit_delivery
Create Date: 2026-05-02 22:02:00.000000

Flow attempt provenance is the canonical owner for LLM tool-call evidence. The
downgrade recreates the nullable result-row column for schema reversibility, but
does not restore data because live Flow result writes already stored this field
as NULL before the column was removed.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260502_drop_result_tool_calls"
down_revision = "20260502_flow_audit_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("flow_step_results", "tool_calls_metadata")


def downgrade() -> None:
    op.add_column(
        "flow_step_results",
        sa.Column("tool_calls_metadata", postgresql.JSONB(), nullable=True),
    )
