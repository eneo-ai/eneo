"""Record transcription requests as Flow provider calls.

A Flow provider call was always a completion call, so the table required a
resolved-input aggregate on the attempt and a token dimension on every
completed row. A transcription request has neither: it runs while the step
input is still being produced, and it is metered in audio seconds.

The call kind now says which surface a row describes, the resolved-input link
moves to its own column so only completion calls need it, and completed
transcription rows carry the audio they sent. Pre-production rows predate the
kind and cannot be classified, so they are removed.

Revision ID: 202608161930_call_transcription
Revises: 202608151200
Create Date: 2026-08-16 19:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202608161930_call_transcription"
down_revision = "202608151200"
branch_labels = None
depends_on = None

_TABLE = "flow_provider_calls"
_EVIDENCE_FOREIGN_KEY = "fk_flow_provider_calls_resolved_inputs"
_KIND_CHECK = "ck_flow_provider_calls_kind"
_KIND_SHAPE_CHECK = "ck_flow_provider_calls_kind_shape"
_INPUT_USAGE_CHECK = "ck_flow_provider_calls_input_usage_shape"
_OUTPUT_USAGE_CHECK = "ck_flow_provider_calls_output_usage_shape"

_LEGACY_INPUT_USAGE_SHAPE = (
    "(input_source IS NULL AND num_tokens_input IS NULL) OR "
    "(input_source = 'not_reported' AND num_tokens_input IS NULL) OR "
    "(input_source IS NOT NULL AND input_source <> 'not_reported' "
    "AND num_tokens_input IS NOT NULL)"
)
_LEGACY_OUTPUT_USAGE_SHAPE = (
    "(output_source IS NULL AND num_tokens_output IS NULL) OR "
    "(output_source = 'not_reported' AND num_tokens_output IS NULL) OR "
    "(output_source IS NOT NULL AND output_source <> 'not_reported' "
    "AND num_tokens_output IS NOT NULL)"
)
_INPUT_USAGE_SHAPE = (
    "(input_source IS NULL AND num_tokens_input IS NULL) OR "
    "(input_source IN ('not_reported', 'not_applicable') "
    "AND num_tokens_input IS NULL) OR "
    "(input_source NOT IN ('not_reported', 'not_applicable') "
    "AND num_tokens_input IS NOT NULL)"
)
_OUTPUT_USAGE_SHAPE = (
    "(output_source IS NULL AND num_tokens_output IS NULL) OR "
    "(output_source IN ('not_reported', 'not_applicable') "
    "AND num_tokens_output IS NULL) OR "
    "(output_source NOT IN ('not_reported', 'not_applicable') "
    "AND num_tokens_output IS NOT NULL)"
)
_KIND_SHAPE = (
    "(call_kind = 'completion' AND audio_seconds IS NULL "
    "AND resolved_inputs_attempt_id = flow_step_attempt_id "
    "AND input_source IS DISTINCT FROM 'not_applicable' "
    "AND output_source IS DISTINCT FROM 'not_applicable') OR "
    "(call_kind = 'transcription' AND audio_seconds IS NOT NULL "
    "AND audio_seconds >= 0 "
    "AND resolved_inputs_attempt_id IS NULL "
    "AND cardinality(resolved_input_edge_indexes) = 0 "
    "AND response_format = 'none' "
    "AND cardinality(requested_capabilities) = 0 "
    "AND call_reason = 'initial' "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NOT DISTINCT FROM "
    "  CASE WHEN status = 'completed' THEN 'not_applicable' END "
    "AND output_source IS NOT DISTINCT FROM "
    "  CASE WHEN status = 'completed' THEN 'not_applicable' END)"
)


def upgrade() -> None:
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    op.execute(f"DELETE FROM {_TABLE}")

    op.drop_constraint(_EVIDENCE_FOREIGN_KEY, _TABLE, type_="foreignkey")
    op.add_column(
        _TABLE, sa.Column("resolved_inputs_attempt_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        _EVIDENCE_FOREIGN_KEY,
        _TABLE,
        "flow_step_attempt_resolved_inputs",
        ["resolved_inputs_attempt_id"],
        ["flow_step_attempt_id"],
    )
    op.add_column(_TABLE, sa.Column("call_kind", sa.String(32), nullable=False))
    op.add_column(_TABLE, sa.Column("audio_seconds", sa.Numeric(12, 3), nullable=True))

    op.create_check_constraint(
        _KIND_CHECK, _TABLE, "call_kind IN ('completion', 'transcription')"
    )
    op.drop_constraint(_INPUT_USAGE_CHECK, _TABLE, type_="check")
    op.drop_constraint(_OUTPUT_USAGE_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_INPUT_USAGE_CHECK, _TABLE, _INPUT_USAGE_SHAPE)
    op.create_check_constraint(_OUTPUT_USAGE_CHECK, _TABLE, _OUTPUT_USAGE_SHAPE)
    op.create_check_constraint(_KIND_SHAPE_CHECK, _TABLE, _KIND_SHAPE)


def downgrade() -> None:
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    op.execute(f"DELETE FROM {_TABLE}")

    op.drop_constraint(_KIND_SHAPE_CHECK, _TABLE, type_="check")
    op.drop_constraint(_INPUT_USAGE_CHECK, _TABLE, type_="check")
    op.drop_constraint(_OUTPUT_USAGE_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_INPUT_USAGE_CHECK, _TABLE, _LEGACY_INPUT_USAGE_SHAPE)
    op.create_check_constraint(_OUTPUT_USAGE_CHECK, _TABLE, _LEGACY_OUTPUT_USAGE_SHAPE)
    op.drop_constraint(_KIND_CHECK, _TABLE, type_="check")

    op.drop_column(_TABLE, "audio_seconds")
    op.drop_column(_TABLE, "call_kind")
    op.drop_constraint(_EVIDENCE_FOREIGN_KEY, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "resolved_inputs_attempt_id")
    op.create_foreign_key(
        _EVIDENCE_FOREIGN_KEY,
        _TABLE,
        "flow_step_attempt_resolved_inputs",
        ["flow_step_attempt_id"],
        ["flow_step_attempt_id"],
    )
