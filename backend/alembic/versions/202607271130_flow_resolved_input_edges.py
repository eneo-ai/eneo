"""Add immutable resolved-input evidence for Flow step attempts.

Revision ID: 202607271130_resolved_edges
Revises: 202607270830_call_capabilities
Create Date: 2026-07-27 11:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607271130_resolved_edges"
down_revision = "202607270830_call_capabilities"
branch_labels = None
depends_on = None

_TABLE = "flow_step_attempt_resolved_inputs"
_COUNT_CONSTRAINT = "ck_flow_step_attempt_resolved_input_count"
_COUNT_EXPRESSION = (
    "CASE WHEN jsonb_typeof(resolved_input_edges_jsonb) = 'object' AND "
    "jsonb_typeof(resolved_input_edges_jsonb -> 'edges') = 'array' "
    "THEN jsonb_array_length(resolved_input_edges_jsonb -> 'edges') "
    "ELSE -1 END"
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "flow_step_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "resolved_input_edges_jsonb",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "resolved_input_edge_count",
            sa.SmallInteger(),
            sa.Computed(_COUNT_EXPRESSION, persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resolved_input_edge_count BETWEEN 0 AND 2048",
            name=_COUNT_CONSTRAINT,
        ),
        sa.ForeignKeyConstraint(
            ["flow_step_attempt_id"],
            ["flow_step_attempts.id"],
            name="fk_flow_step_attempt_resolved_inputs_attempt",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "flow_step_attempt_id",
            name="pk_flow_step_attempt_resolved_inputs",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {_TABLE})")):
        raise RuntimeError(
            "Cannot downgrade while resolved-input evidence would be discarded."
        )
    op.drop_table(_TABLE)
