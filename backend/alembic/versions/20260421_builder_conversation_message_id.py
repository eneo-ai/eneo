"""backfill stable message_id on every builder_sessions.conversation entry

Revision ID: 20260421_builder_conv_msg_id
Revises: 20260419_builder_tenant_guard
Create Date: 2026-04-21 00:10:00.000000

Downstream consumers reference conversation messages by stable id instead
of positional index (indices break after compaction). This migration
backfills a random UUID on every existing conversation entry that lacks
`message_id`. New messages get a UUIDv7 from
`ConversationMessage._new_message_id`; legacy rows get an ordinary v4 —
the contract is stability, not time-ordering.

The migration refuses to run if any row has a non-array `conversation` or
any element that is not a JSON object. Pre-release: fix by hand, no
rescue logic.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260421_builder_conv_msg_id"
down_revision = "20260419_builder_tenant_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Shape check first: no SRF here, so this is safe on any JSONB value. We
    # bail before running the element check (which uses `jsonb_array_elements`)
    # so a scalar/null `conversation` cannot reach the SRF and surface a raw
    # Postgres error instead of our RuntimeError.
    shape_bad = conn.execute(
        sa.text(
            "SELECT 1 FROM builder_sessions "
            "WHERE conversation IS NULL "
            "OR jsonb_typeof(conversation) <> 'array' "
            "LIMIT 1"
        )
    ).scalar()
    if shape_bad is not None:
        raise RuntimeError(
            "Cannot backfill conversation message_id: at least one "
            "builder_sessions row has a NULL or non-array conversation. "
            "Fix by hand before re-running this migration."
        )
    element_bad = conn.execute(
        sa.text(
            "SELECT 1 FROM builder_sessions "
            "WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements(conversation) AS msg "
            "  WHERE jsonb_typeof(msg) <> 'object'"
            ") "
            "LIMIT 1"
        )
    ).scalar()
    if element_bad is not None:
        raise RuntimeError(
            "Cannot backfill conversation message_id: at least one "
            "builder_sessions row has a non-object element in its "
            "conversation. Fix by hand before re-running this migration."
        )
    op.execute(
        sa.text(
            "UPDATE builder_sessions "
            "SET conversation = ("
            "  SELECT jsonb_agg("
            "    CASE WHEN msg ? 'message_id' THEN msg "
            "         ELSE msg || jsonb_build_object('message_id', gen_random_uuid()::text) "
            "    END "
            "    ORDER BY ord"
            "  ) "
            "  FROM jsonb_array_elements(conversation) WITH ORDINALITY AS t(msg, ord)"
            ") "
            "WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements(conversation) AS m "
            "  WHERE NOT (m ? 'message_id')"
            ")"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE builder_sessions "
            "SET conversation = ("
            "  SELECT COALESCE(jsonb_agg(msg - 'message_id' ORDER BY ord), '[]'::jsonb) "
            "  FROM jsonb_array_elements(conversation) WITH ORDINALITY AS t(msg, ord)"
            ") "
            "WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements(conversation) AS m "
            "  WHERE m ? 'message_id'"
            ")"
        )
    )
