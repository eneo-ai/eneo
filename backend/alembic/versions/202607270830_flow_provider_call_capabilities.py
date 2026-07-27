"""Record requested capabilities for each observed Flow provider call.

Revision ID: 202607270830_call_capabilities
Revises: 202607261600_provider_calls
Create Date: 2026-07-27 08:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607270830_call_capabilities"
down_revision = "202607261600_provider_calls"
branch_labels = None
depends_on = None

_ALLOWED_CONSTRAINT = "ck_flow_provider_calls_capabilities_allowed"
_RESPONSE_FORMAT_CONSTRAINT = "ck_flow_provider_calls_capabilities_response_format"


def upgrade() -> None:
    op.add_column(
        "flow_provider_calls",
        sa.Column(
            "requested_capabilities",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        _ALLOWED_CONSTRAINT,
        "flow_provider_calls",
        "requested_capabilities IS NULL OR ("
        "(cardinality(requested_capabilities) = 0 OR "
        "array_ndims(requested_capabilities) = 1) AND "
        "requested_capabilities <@ ARRAY["
        "'image_input', 'reasoning', 'structured_output', 'tool_calling'"
        "]::varchar(32)[] AND cardinality(requested_capabilities) <= 4)",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        _RESPONSE_FORMAT_CONSTRAINT,
        "flow_provider_calls",
        "requested_capabilities IS NULL OR (response_format IS NOT NULL AND "
        "(('structured_output' = ANY(requested_capabilities)) = "
        "(response_format IN ('json_object', 'json_schema'))))",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE flow_provider_calls VALIDATE CONSTRAINT {_ALLOWED_CONSTRAINT}"
    )
    op.execute(
        "ALTER TABLE flow_provider_calls VALIDATE CONSTRAINT "
        f"{_RESPONSE_FORMAT_CONSTRAINT}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    observed_row_exists = bind.scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM flow_provider_calls "
            "WHERE requested_capabilities IS NOT NULL)"
        )
    )
    if observed_row_exists:
        raise RuntimeError(
            "Cannot downgrade while requested capability evidence would be discarded."
        )

    op.drop_constraint(
        _RESPONSE_FORMAT_CONSTRAINT,
        "flow_provider_calls",
        type_="check",
    )
    op.drop_constraint(
        _ALLOWED_CONSTRAINT,
        "flow_provider_calls",
        type_="check",
    )
    op.drop_column("flow_provider_calls", "requested_capabilities")
