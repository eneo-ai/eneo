"""Link Flow provider calls to their resolved input evidence.

Existing pre-production provider-call rows cannot be linked truthfully because
their runtime input groups were not recorded. Upgrade removes those rows before
requiring a bounded index set on every newly observed call.

Revision ID: 202607271700_call_input_indexes
Revises: 202607271530_provider_call_v2
Create Date: 2026-07-27 17:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607271700_call_input_indexes"
down_revision = "202607271530_provider_call_v2"
branch_labels = None
depends_on = None

_TABLE = "flow_provider_calls"
_INDEXES_COLUMN = "resolved_input_edge_indexes"
_INDEXES_CONSTRAINT = "ck_flow_provider_calls_resolved_input_indexes"
_EVIDENCE_FOREIGN_KEY = "fk_flow_provider_calls_resolved_inputs"
_MAX_RESOLVED_INPUT_EDGES = 2048


def upgrade() -> None:
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    op.execute(f"DELETE FROM {_TABLE}")
    op.add_column(
        _TABLE,
        sa.Column(
            _INDEXES_COLUMN,
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        _INDEXES_CONSTRAINT,
        _TABLE,
        "(cardinality(resolved_input_edge_indexes) = 0 OR "
        "array_ndims(resolved_input_edge_indexes) = 1) AND "
        "array_position(resolved_input_edge_indexes, NULL) IS NULL AND "
        f"cardinality(resolved_input_edge_indexes) <= {_MAX_RESOLVED_INPUT_EDGES} "
        "AND 0 <= ALL(resolved_input_edge_indexes) AND "
        f"{_MAX_RESOLVED_INPUT_EDGES} > ALL(resolved_input_edge_indexes)",
    )
    op.create_foreign_key(
        _EVIDENCE_FOREIGN_KEY,
        _TABLE,
        "flow_step_attempt_resolved_inputs",
        ["flow_step_attempt_id"],
        ["flow_step_attempt_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    row_count = bind.scalar(sa.text(f"SELECT count(*) FROM {_TABLE}"))
    if row_count:
        raise RuntimeError(
            "Cannot downgrade while provider-call resolved-input links would be "
            f"discarded ({row_count} rows); delete them explicitly or roll forward."
        )
    op.drop_constraint(_EVIDENCE_FOREIGN_KEY, _TABLE, type_="foreignkey")
    op.drop_constraint(_INDEXES_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, _INDEXES_COLUMN)
