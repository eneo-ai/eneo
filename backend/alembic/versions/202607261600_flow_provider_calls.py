"""Create attempt-scoped Flow provider-call lifecycle evidence.

This pre-release migration was amended to create the final version-two schema
directly. ``202607271530_provider_call_v2`` converges development databases that
applied the earlier version-one shape before this amendment.

Revision ID: 202607261600_provider_calls
Revises: 202607250930_rerun_input_chain
Create Date: 2026-07-26 16:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607261600_provider_calls"
down_revision = "202607250930_rerun_input_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_provider_calls",
        sa.Column(
            "flow_step_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("provider_request_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_model", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("response_format", sa.String(length=32), nullable=False),
        sa.Column("call_reason", sa.String(length=32), nullable=False),
        sa.Column("mapped_execution_mode", sa.String(length=32), nullable=True),
        sa.Column("mapped_item_index", sa.Integer(), nullable=True),
        sa.Column("mapped_source_index", sa.Integer(), nullable=True),
        sa.Column("mapped_source_id", sa.Text(), nullable=True),
        sa.Column("response_model", sa.String(length=255), nullable=True),
        sa.Column("provider_response_id", sa.String(length=512), nullable=True),
        sa.Column("num_tokens_input", sa.Integer(), nullable=True),
        sa.Column("num_tokens_output", sa.Integer(), nullable=True),
        sa.Column("input_source", sa.String(length=32), nullable=True),
        sa.Column("output_source", sa.String(length=32), nullable=True),
        sa.Column("outcome_reason", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ordinal >= 1", name="ck_flow_provider_calls_ordinal_positive"
        ),
        sa.CheckConstraint(
            "status IN ('started', 'completed', 'rejected', 'outcome_unknown')",
            name="ck_flow_provider_calls_status",
        ),
        sa.CheckConstraint(
            "response_format IN ('none', 'json_object', 'json_schema', 'other')",
            name="ck_flow_provider_calls_response_format",
        ),
        sa.CheckConstraint(
            "call_reason IN ('initial', 'response_format_fallback', 'tool_round')",
            name="ck_flow_provider_calls_reason",
        ),
        sa.CheckConstraint(
            "request_schema_version = 2 AND provider_request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_flow_provider_calls_request_identity",
        ),
        sa.CheckConstraint(
            "length(requested_model) > 0",
            name="ck_flow_provider_calls_requested_model_nonempty",
        ),
        sa.CheckConstraint(
            "provider IS NULL OR length(provider) > 0",
            name="ck_flow_provider_calls_provider_nonempty",
        ),
        sa.CheckConstraint(
            "num_tokens_input IS NULL OR num_tokens_input >= 0",
            name="ck_flow_provider_calls_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "num_tokens_output IS NULL OR num_tokens_output >= 0",
            name="ck_flow_provider_calls_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "input_source IS NULL OR input_source IN "
            "('provider', 'estimated', 'mixed', 'not_applicable', 'not_reported')",
            name="ck_flow_provider_calls_input_source",
        ),
        sa.CheckConstraint(
            "output_source IS NULL OR output_source IN "
            "('provider', 'estimated', 'mixed', 'not_applicable', 'not_reported')",
            name="ck_flow_provider_calls_output_source",
        ),
        sa.CheckConstraint(
            "(input_source IS NULL AND num_tokens_input IS NULL) OR "
            "(input_source = 'not_reported' AND num_tokens_input IS NULL) OR "
            "(input_source IS NOT NULL AND input_source <> 'not_reported' "
            "AND num_tokens_input IS NOT NULL)",
            name="ck_flow_provider_calls_input_usage_shape",
        ),
        sa.CheckConstraint(
            "(output_source IS NULL AND num_tokens_output IS NULL) OR "
            "(output_source = 'not_reported' AND num_tokens_output IS NULL) OR "
            "(output_source IS NOT NULL AND output_source <> 'not_reported' "
            "AND num_tokens_output IS NOT NULL)",
            name="ck_flow_provider_calls_output_usage_shape",
        ),
        sa.CheckConstraint(
            "(status = 'started' AND finished_at IS NULL AND outcome_reason IS NULL "
            "AND response_model IS NULL AND provider_response_id IS NULL "
            "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
            "AND input_source IS NULL AND output_source IS NULL) OR "
            "(status = 'completed' AND finished_at IS NOT NULL "
            "AND outcome_reason IS NULL AND input_source IS NOT NULL "
            "AND output_source IS NOT NULL) OR "
            "(status = 'rejected' AND finished_at IS NOT NULL "
            "AND outcome_reason IN ('response_format_rejected', 'provider_rejected') "
            "AND response_model IS NULL AND provider_response_id IS NULL "
            "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
            "AND input_source IS NULL AND output_source IS NULL) OR "
            "(status = 'outcome_unknown' AND finished_at IS NOT NULL "
            "AND outcome_reason IN ('request_timeout', 'run_cancelled', "
            "'worker_interrupted', 'provider_error', 'request_cancelled', "
            "'stale_started') AND response_model IS NULL "
            "AND provider_response_id IS NULL AND num_tokens_input IS NULL "
            "AND num_tokens_output IS NULL AND input_source IS NULL "
            "AND output_source IS NULL)",
            name="ck_flow_provider_calls_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "(mapped_execution_mode IS NULL AND mapped_item_index IS NULL "
            "AND mapped_source_index IS NULL AND mapped_source_id IS NULL) OR "
            "(mapped_execution_mode = 'per_item' AND mapped_item_index >= 1 "
            "AND mapped_source_index IS NULL) OR "
            "(mapped_execution_mode = 'per_source' AND mapped_source_index >= 1 "
            "AND mapped_item_index IS NULL)",
            name="ck_flow_provider_calls_mapped_context",
        ),
        sa.ForeignKeyConstraint(
            ["flow_step_attempt_id"],
            ["flow_step_attempts.id"],
            name="fk_flow_provider_calls_attempt",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_flow_provider_calls"),
        sa.UniqueConstraint(
            "flow_step_attempt_id",
            "ordinal",
            name="uq_flow_provider_calls_attempt_ordinal",
        ),
    )
    op.create_index(
        "ix_flow_provider_calls_started_requested_at",
        "flow_provider_calls",
        ["requested_at"],
        unique=False,
        postgresql_where=sa.text("status = 'started'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    row_count = bind.scalar(sa.text("SELECT count(*) FROM flow_provider_calls"))
    if row_count:
        raise RuntimeError(
            "flow_provider_calls downgrade would discard provider lifecycle "
            f"evidence ({row_count} rows); delete it explicitly or roll forward"
        )
    op.drop_index(
        "ix_flow_provider_calls_started_requested_at",
        table_name="flow_provider_calls",
    )
    op.drop_table("flow_provider_calls")
