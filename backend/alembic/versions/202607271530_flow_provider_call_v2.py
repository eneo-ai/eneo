"""Converge Flow provider-call evidence on the version-two request contract.

Pre-production databases may contain rows written by the superseded version-one
observer. Those hashes cannot be relabelled because version two includes provider
identity, so upgrade deletes those development rows before tightening the schema.

Revision ID: 202607271530_provider_call_v2
Revises: 202607271130_resolved_edges
Create Date: 2026-07-27 15:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202607271530_provider_call_v2"
down_revision = "202607271130_resolved_edges"
branch_labels = None
depends_on = None

_CAPABILITIES_ALLOWED = "ck_flow_provider_calls_capabilities_allowed"
_CAPABILITIES_RESPONSE_FORMAT = "ck_flow_provider_calls_capabilities_response_format"
_EVIDENCE_SHAPE = "ck_flow_provider_calls_evidence_shape"
_EVIDENCE_SOURCE = "ck_flow_provider_calls_evidence_source"
_LIFECYCLE_SHAPE = "ck_flow_provider_calls_lifecycle_shape"
_PROVIDER_NONEMPTY = "ck_flow_provider_calls_provider_nonempty"
_REQUEST_IDENTITY = "ck_flow_provider_calls_request_identity"
_REQUESTED_MODEL_NONEMPTY = "ck_flow_provider_calls_requested_model_nonempty"
_REASON = "ck_flow_provider_calls_reason"
_RESPONSE_FORMAT = "ck_flow_provider_calls_response_format"


def _check_constraint_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(constraint["name"])
        for constraint in inspector.get_check_constraints("flow_provider_calls")
        if constraint.get("name") is not None
    }


def _column_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(column["name"]) for column in inspector.get_columns("flow_provider_calls")
    }


def _drop_check_constraints(*names: str) -> None:
    existing = _check_constraint_names()
    for name in names:
        if name in existing:
            op.drop_constraint(name, "flow_provider_calls", type_="check")


def _create_check(name: str, condition: str) -> None:
    op.create_check_constraint(name, "flow_provider_calls", condition)


def upgrade() -> None:
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DELETE FROM flow_provider_calls
        WHERE request_schema_version IS DISTINCT FROM 2
           OR provider_request_hash IS NULL
           OR requested_model IS NULL
           OR length(requested_model) = 0
           OR provider = ''
           OR response_format IS NULL
           OR requested_capabilities IS NULL
           OR requested_at IS NULL
        """
    )

    _drop_check_constraints(
        _CAPABILITIES_ALLOWED,
        _CAPABILITIES_RESPONSE_FORMAT,
        _EVIDENCE_SHAPE,
        _EVIDENCE_SOURCE,
        _LIFECYCLE_SHAPE,
        _PROVIDER_NONEMPTY,
        _REQUEST_IDENTITY,
        _REQUESTED_MODEL_NONEMPTY,
        _REASON,
        _RESPONSE_FORMAT,
    )
    if "evidence_source" in _column_names():
        op.drop_column("flow_provider_calls", "evidence_source")

    for column_name, existing_type in (
        ("request_schema_version", sa.SmallInteger()),
        ("provider_request_hash", sa.String(length=64)),
        ("requested_model", sa.String(length=255)),
        ("response_format", sa.String(length=32)),
        ("requested_at", sa.DateTime(timezone=True)),
    ):
        op.alter_column(
            "flow_provider_calls",
            column_name,
            existing_type=existing_type,
            nullable=False,
        )
    op.alter_column(
        "flow_provider_calls",
        "requested_capabilities",
        existing_type=sa.ARRAY(sa.String(length=32)),
        nullable=False,
    )

    _create_check(
        _RESPONSE_FORMAT,
        "response_format IN ('none', 'json_object', 'json_schema', 'other')",
    )
    _create_check(
        _REASON,
        "call_reason IN ('initial', 'response_format_fallback', 'tool_round')",
    )
    _create_check(
        _REQUEST_IDENTITY,
        "request_schema_version = 2 AND provider_request_hash ~ '^[0-9a-f]{64}$'",
    )
    _create_check(
        _REQUESTED_MODEL_NONEMPTY,
        "length(requested_model) > 0",
    )
    _create_check(
        _PROVIDER_NONEMPTY,
        "provider IS NULL OR length(provider) > 0",
    )
    _create_check(
        _CAPABILITIES_ALLOWED,
        "(cardinality(requested_capabilities) = 0 OR "
        "array_ndims(requested_capabilities) = 1) AND "
        "requested_capabilities <@ ARRAY["
        "'image_input', 'reasoning', 'structured_output', 'tool_calling'"
        "]::varchar(32)[] AND cardinality(requested_capabilities) <= 4",
    )
    _create_check(
        _CAPABILITIES_RESPONSE_FORMAT,
        "(('structured_output' = ANY(requested_capabilities)) = "
        "(response_format IN ('json_object', 'json_schema')))",
    )
    _create_check(
        _LIFECYCLE_SHAPE,
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
    )


def downgrade() -> None:
    # This reconstruction defines the superseded post-capabilities schema used
    # by the convergence proof; it is not a supported runtime compatibility path.
    bind = op.get_bind()
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    row_count = bind.scalar(sa.text("SELECT count(*) FROM flow_provider_calls"))
    if row_count:
        raise RuntimeError(
            "provider-call version-two downgrade cannot reconstruct superseded "
            f"request evidence ({row_count} rows); delete it explicitly or roll forward"
        )

    _drop_check_constraints(
        _CAPABILITIES_ALLOWED,
        _CAPABILITIES_RESPONSE_FORMAT,
        _LIFECYCLE_SHAPE,
        _PROVIDER_NONEMPTY,
        _REQUEST_IDENTITY,
        _REQUESTED_MODEL_NONEMPTY,
        _REASON,
        _RESPONSE_FORMAT,
    )
    op.add_column(
        "flow_provider_calls",
        sa.Column("evidence_source", sa.String(length=32), nullable=False),
    )
    for column_name, existing_type in (
        ("request_schema_version", sa.SmallInteger()),
        ("provider_request_hash", sa.String(length=64)),
        ("requested_model", sa.String(length=255)),
        ("response_format", sa.String(length=32)),
        ("requested_at", sa.DateTime(timezone=True)),
    ):
        op.alter_column(
            "flow_provider_calls",
            column_name,
            existing_type=existing_type,
            nullable=True,
        )
    op.alter_column(
        "flow_provider_calls",
        "requested_capabilities",
        existing_type=sa.ARRAY(sa.String(length=32)),
        nullable=True,
    )
    _create_check(
        _EVIDENCE_SOURCE,
        "evidence_source IN ('live_observer', 'legacy_provenance')",
    )
    _create_check(
        _RESPONSE_FORMAT,
        "response_format IS NULL OR response_format IN "
        "('none', 'json_object', 'json_schema', 'other')",
    )
    _create_check(
        _REASON,
        "call_reason IN ('initial', 'response_format_fallback', 'tool_round', "
        "'legacy_backfill')",
    )
    _create_check(
        _REQUEST_IDENTITY,
        "(request_schema_version IS NULL AND provider_request_hash IS NULL) OR "
        "(request_schema_version = 1 AND "
        "provider_request_hash ~ '^[0-9a-f]{64}$')",
    )
    _create_check(
        _CAPABILITIES_ALLOWED,
        "requested_capabilities IS NULL OR ("
        "(cardinality(requested_capabilities) = 0 OR "
        "array_ndims(requested_capabilities) = 1) AND "
        "requested_capabilities <@ ARRAY["
        "'image_input', 'reasoning', 'structured_output', 'tool_calling'"
        "]::varchar(32)[] AND cardinality(requested_capabilities) <= 4)",
    )
    _create_check(
        _CAPABILITIES_RESPONSE_FORMAT,
        "requested_capabilities IS NULL OR (response_format IS NOT NULL AND "
        "(('structured_output' = ANY(requested_capabilities)) = "
        "(response_format IN ('json_object', 'json_schema'))))",
    )
    _create_check(
        _LIFECYCLE_SHAPE,
        "(status = 'started' AND finished_at IS NULL AND outcome_reason IS NULL "
        "AND response_model IS NULL AND provider_response_id IS NULL "
        "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
        "AND input_source IS NULL AND output_source IS NULL) OR "
        "(status = 'completed' AND outcome_reason IS NULL "
        "AND input_source IS NOT NULL AND output_source IS NOT NULL "
        "AND ((evidence_source = 'legacy_provenance') OR "
        "(finished_at IS NOT NULL))) OR "
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
    )
    _create_check(
        _EVIDENCE_SHAPE,
        "(evidence_source = 'live_observer' AND response_format IS NOT NULL "
        "AND request_schema_version = 1 "
        "AND provider_request_hash IS NOT NULL AND requested_at IS NOT NULL "
        "AND call_reason <> 'legacy_backfill') OR "
        "(evidence_source = 'legacy_provenance' AND status = 'completed' "
        "AND response_format IS NULL "
        "AND request_schema_version IS NULL AND provider_request_hash IS NULL "
        "AND requested_at IS NULL AND finished_at IS NULL "
        "AND call_reason = 'legacy_backfill')",
    )
