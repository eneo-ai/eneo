"""Move Flow provider-call lifecycle evidence into an attempt-scoped table.

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


def _abort_if_open_attempts() -> None:
    bind = op.get_bind()
    op.execute("LOCK TABLE flow_step_attempts IN SHARE ROW EXCLUSIVE MODE")
    open_attempt_count = bind.scalar(
        sa.text("SELECT count(*) FROM flow_step_attempts WHERE status = 'started'")
    )
    if open_attempt_count:
        raise RuntimeError(
            "flow_provider_calls migration requires drained Flow workers: "
            f"found {open_attempt_count} started flow_step_attempts"
        )


def _abort_if_invalid_legacy_receipts() -> None:
    bind = op.get_bind()
    invalid = (
        bind.execute(
            sa.text(
                """
            WITH legacy AS (
                SELECT
                    id,
                    provenance_json #> '{token_usage,completed_provider_calls}' AS receipts
                FROM flow_step_attempts
                WHERE provenance_json #> '{token_usage,completed_provider_calls}' IS NOT NULL
            ), expanded AS (
                SELECT legacy.id, expanded_receipt.receipt, expanded_receipt.ordinal
                FROM legacy
                LEFT JOIN LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(legacy.receipts) = 'array' THEN legacy.receipts
                        ELSE '[]'::jsonb
                    END
                ) WITH ORDINALITY AS expanded_receipt(receipt, ordinal) ON TRUE
            ), classified AS (
                SELECT
                    legacy.id,
                    jsonb_typeof(legacy.receipts) <> 'array' AS non_array,
                    receipt IS NOT NULL AND (
                        jsonb_typeof(receipt) IS DISTINCT FROM 'object'
                        OR jsonb_typeof(receipt -> 'call_index')
                            IS DISTINCT FROM 'number'
                        OR (receipt ->> 'call_index') !~ '^[1-9][0-9]*$'
                        OR CASE
                            WHEN (receipt ->> 'call_index') ~ '^[1-9][0-9]*$'
                            THEN (receipt ->> 'call_index')::numeric > 2147483647
                            ELSE false
                        END
                    ) AS invalid_item,
                    jsonb_typeof(receipt) = 'object'
                        AND jsonb_typeof(receipt -> 'call_index') = 'number'
                        AND (receipt ->> 'call_index') ~ '^[1-9][0-9]*$'
                        AND (receipt ->> 'call_index')
                            IS DISTINCT FROM ordinal::text
                        AS invalid_ordinal,
                    CASE
                        WHEN jsonb_typeof(receipt) IS DISTINCT FROM 'object' THEN false
                        ELSE (
                            jsonb_typeof(receipt -> 'input_source')
                                IS DISTINCT FROM 'string'
                            OR receipt ->> 'input_source' NOT IN (
                                'provider', 'estimated', 'mixed', 'not_applicable',
                                'not_reported'
                            )
                            OR jsonb_typeof(receipt -> 'output_source')
                                IS DISTINCT FROM 'string'
                            OR receipt ->> 'output_source' NOT IN (
                                'provider', 'estimated', 'mixed', 'not_applicable',
                                'not_reported'
                            )
                            OR CASE
                                WHEN receipt -> 'num_tokens_input' IS NULL
                                    OR jsonb_typeof(receipt -> 'num_tokens_input') = 'null'
                                THEN receipt ->> 'input_source'
                                    IS DISTINCT FROM 'not_reported'
                                WHEN jsonb_typeof(receipt -> 'num_tokens_input') = 'number'
                                    AND (receipt ->> 'num_tokens_input')
                                        ~ '^(0|[1-9][0-9]*)$'
                                THEN receipt ->> 'input_source' = 'not_reported'
                                    OR (receipt ->> 'num_tokens_input')::numeric
                                        > 2147483647
                                ELSE true
                            END
                            OR CASE
                                WHEN receipt -> 'num_tokens_output' IS NULL
                                    OR jsonb_typeof(receipt -> 'num_tokens_output') = 'null'
                                THEN receipt ->> 'output_source'
                                    IS DISTINCT FROM 'not_reported'
                                WHEN jsonb_typeof(receipt -> 'num_tokens_output') = 'number'
                                    AND (receipt ->> 'num_tokens_output')
                                        ~ '^(0|[1-9][0-9]*)$'
                                THEN receipt ->> 'output_source' = 'not_reported'
                                    OR (receipt ->> 'num_tokens_output')::numeric
                                        > 2147483647
                                ELSE true
                            END
                        )
                    END AS invalid_token_usage,
                    CASE
                        WHEN jsonb_typeof(receipt) IS DISTINCT FROM 'object' THEN false
                        ELSE (
                            (
                                receipt -> 'requested_model' IS NOT NULL
                                AND jsonb_typeof(receipt -> 'requested_model') <> 'null'
                                AND (
                                    jsonb_typeof(receipt -> 'requested_model')
                                        IS DISTINCT FROM 'string'
                                    OR length(receipt ->> 'requested_model') > 255
                                )
                            )
                            OR (
                                receipt -> 'response_model' IS NOT NULL
                                AND jsonb_typeof(receipt -> 'response_model') <> 'null'
                                AND (
                                    jsonb_typeof(receipt -> 'response_model')
                                        IS DISTINCT FROM 'string'
                                    OR length(receipt ->> 'response_model') > 255
                                )
                            )
                            OR (
                                receipt -> 'provider' IS NOT NULL
                                AND jsonb_typeof(receipt -> 'provider') <> 'null'
                                AND (
                                    jsonb_typeof(receipt -> 'provider')
                                        IS DISTINCT FROM 'string'
                                    OR length(receipt ->> 'provider') > 128
                                )
                            )
                            OR (
                                receipt -> 'provider_response_id' IS NOT NULL
                                AND jsonb_typeof(receipt -> 'provider_response_id')
                                    <> 'null'
                                AND (
                                    jsonb_typeof(receipt -> 'provider_response_id')
                                        IS DISTINCT FROM 'string'
                                    OR length(receipt ->> 'provider_response_id') > 512
                                )
                            )
                            OR (
                                receipt #> '{mapped_call,source_id}' IS NOT NULL
                                AND jsonb_typeof(
                                    receipt #> '{mapped_call,source_id}'
                                ) NOT IN ('null', 'string')
                            )
                            OR CASE
                                WHEN receipt -> 'mapped_call' IS NULL
                                    OR jsonb_typeof(receipt -> 'mapped_call') = 'null'
                                THEN false
                                WHEN jsonb_typeof(receipt -> 'mapped_call')
                                    IS DISTINCT FROM 'object'
                                THEN true
                                WHEN receipt #>> '{mapped_call,execution_mode}' = 'per_item'
                                THEN
                                    jsonb_typeof(receipt #> '{mapped_call,item_index}')
                                        IS DISTINCT FROM 'number'
                                    OR (receipt #>> '{mapped_call,item_index}')
                                        !~ '^[1-9][0-9]*$'
                                    OR CASE
                                        WHEN (receipt #>> '{mapped_call,item_index}')
                                            ~ '^[1-9][0-9]*$'
                                        THEN (receipt #>> '{mapped_call,item_index}')::numeric
                                            > 2147483647
                                        ELSE false
                                    END
                                    OR (
                                        receipt #> '{mapped_call,source_index}' IS NOT NULL
                                        AND jsonb_typeof(
                                            receipt #> '{mapped_call,source_index}'
                                        ) <> 'null'
                                    )
                                WHEN receipt #>> '{mapped_call,execution_mode}' =
                                    'per_source_reader'
                                THEN
                                    jsonb_typeof(receipt #> '{mapped_call,source_index}')
                                        IS DISTINCT FROM 'number'
                                    OR (receipt #>> '{mapped_call,source_index}')
                                        !~ '^[1-9][0-9]*$'
                                    OR CASE
                                        WHEN (receipt #>> '{mapped_call,source_index}')
                                            ~ '^[1-9][0-9]*$'
                                        THEN (receipt #>> '{mapped_call,source_index}')::numeric
                                            > 2147483647
                                        ELSE false
                                    END
                                    OR (
                                        receipt #> '{mapped_call,item_index}' IS NOT NULL
                                        AND jsonb_typeof(
                                            receipt #> '{mapped_call,item_index}'
                                        ) <> 'null'
                                    )
                                ELSE true
                            END
                        )
                    END AS invalid_fields
                FROM legacy
                LEFT JOIN expanded USING (id)
            )
            SELECT
                count(*) FILTER (WHERE non_array) AS non_array_count,
                count(*) FILTER (WHERE invalid_item) AS invalid_item_count,
                count(*) FILTER (WHERE invalid_ordinal) AS invalid_ordinal_count,
                count(*) FILTER (
                    WHERE invalid_token_usage
                ) AS invalid_token_usage_count,
                count(*) FILTER (WHERE invalid_fields) AS invalid_field_count,
                min(id::text) FILTER (
                    WHERE non_array OR invalid_item OR invalid_ordinal
                        OR invalid_token_usage OR invalid_fields
                ) AS example_attempt_id
            FROM classified
            """
            )
        )
        .mappings()
        .one()
    )
    if (
        invalid["non_array_count"]
        or invalid["invalid_item_count"]
        or invalid["invalid_ordinal_count"]
        or invalid["invalid_token_usage_count"]
        or invalid["invalid_field_count"]
    ):
        raise RuntimeError(
            "flow_provider_calls migration found invalid legacy provider receipts: "
            f"non_array={invalid['non_array_count']}, "
            f"invalid_items={invalid['invalid_item_count']}, "
            f"invalid_ordinals={invalid['invalid_ordinal_count']}, "
            f"invalid_token_usage={invalid['invalid_token_usage_count']}, "
            f"invalid_fields={invalid['invalid_field_count']}, "
            f"example_attempt_id={invalid['example_attempt_id']}"
        )


def _backfill_legacy_receipts() -> None:
    op.execute(
        """
        INSERT INTO flow_provider_calls (
            id,
            flow_step_attempt_id,
            ordinal,
            status,
            evidence_source,
            request_schema_version,
            provider_request_hash,
            requested_model,
            provider,
            response_format,
            call_reason,
            mapped_execution_mode,
            mapped_item_index,
            mapped_source_index,
            mapped_source_id,
            response_model,
            provider_response_id,
            num_tokens_input,
            num_tokens_output,
            input_source,
            output_source,
            outcome_reason,
            requested_at,
            finished_at,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            attempt.id,
            (receipt ->> 'call_index')::integer,
            'completed',
            'legacy_provenance',
            NULL,
            NULL,
            COALESCE(receipt ->> 'requested_model', attempt.requested_model),
            COALESCE(receipt ->> 'provider', attempt.provider),
            NULL,
            'legacy_backfill',
            CASE receipt #>> '{mapped_call,execution_mode}'
                WHEN 'per_source_reader' THEN 'per_source'
                ELSE receipt #>> '{mapped_call,execution_mode}'
            END,
            NULLIF(receipt #>> '{mapped_call,item_index}', '')::integer,
            NULLIF(receipt #>> '{mapped_call,source_index}', '')::integer,
            receipt #>> '{mapped_call,source_id}',
            receipt ->> 'response_model',
            receipt ->> 'provider_response_id',
            NULLIF(receipt ->> 'num_tokens_input', '')::integer,
            NULLIF(receipt ->> 'num_tokens_output', '')::integer,
            receipt ->> 'input_source',
            receipt ->> 'output_source',
            NULL,
            NULL,
            NULL,
            now(),
            now()
        FROM flow_step_attempts AS attempt
        CROSS JOIN LATERAL jsonb_array_elements(
            attempt.provenance_json #> '{token_usage,completed_provider_calls}'
        ) AS receipt
        WHERE jsonb_typeof(
            attempt.provenance_json #> '{token_usage,completed_provider_calls}'
        ) = 'array'
        """
    )


def upgrade() -> None:
    _abort_if_open_attempts()
    _abort_if_invalid_legacy_receipts()
    op.create_table(
        "flow_provider_calls",
        sa.Column(
            "flow_step_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_source", sa.String(length=32), nullable=False),
        sa.Column("request_schema_version", sa.SmallInteger(), nullable=True),
        sa.Column("provider_request_hash", sa.String(length=64), nullable=True),
        sa.Column("requested_model", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("response_format", sa.String(length=32), nullable=True),
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
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
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
            "evidence_source IN ('live_observer', 'legacy_provenance')",
            name="ck_flow_provider_calls_evidence_source",
        ),
        sa.CheckConstraint(
            "response_format IS NULL OR response_format IN "
            "('none', 'json_object', 'json_schema', 'other')",
            name="ck_flow_provider_calls_response_format",
        ),
        sa.CheckConstraint(
            "call_reason IN ('initial', 'response_format_fallback', 'tool_round', "
            "'legacy_backfill')",
            name="ck_flow_provider_calls_reason",
        ),
        sa.CheckConstraint(
            "(request_schema_version IS NULL AND provider_request_hash IS NULL) OR "
            "(request_schema_version = 1 AND provider_request_hash ~ '^[0-9a-f]{64}$')",
            name="ck_flow_provider_calls_request_identity",
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
            "'stale_started') "
            "AND response_model IS NULL AND provider_response_id IS NULL "
            "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
            "AND input_source IS NULL AND output_source IS NULL)",
            name="ck_flow_provider_calls_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "(evidence_source = 'live_observer' AND response_format IS NOT NULL "
            "AND request_schema_version = 1 "
            "AND provider_request_hash IS NOT NULL AND requested_at IS NOT NULL "
            "AND call_reason <> 'legacy_backfill') OR "
            "(evidence_source = 'legacy_provenance' AND status = 'completed' "
            "AND response_format IS NULL "
            "AND request_schema_version IS NULL AND provider_request_hash IS NULL "
            "AND requested_at IS NULL AND finished_at IS NULL "
            "AND call_reason = 'legacy_backfill')",
            name="ck_flow_provider_calls_evidence_shape",
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
    _backfill_legacy_receipts()


def downgrade() -> None:
    bind = op.get_bind()
    live_row_count = bind.scalar(
        sa.text(
            "SELECT count(*) FROM flow_provider_calls "
            "WHERE evidence_source = 'live_observer'"
        )
    )
    if live_row_count:
        raise RuntimeError(
            "flow_provider_calls downgrade would discard live provider lifecycle "
            f"evidence ({live_row_count} rows); roll forward instead"
        )
    op.drop_index(
        "ix_flow_provider_calls_started_requested_at",
        table_name="flow_provider_calls",
    )
    op.drop_table("flow_provider_calls")
