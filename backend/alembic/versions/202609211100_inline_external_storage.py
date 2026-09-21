"""Store fresh inline payloads without TOAST compression.

Revision ID: 202609211100
Revises: 202609211000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609211100"
down_revision = "202609211000"
branch_labels = None
depends_on = None

_PROGRESS_COLUMNS = (
    sa.Column("inline_conversion_cursor_id", sa.UUID(), nullable=True),
    sa.Column("inline_conversion_upper_id", sa.UUID(), nullable=True),
    sa.Column(
        "inline_conversion_scanned", sa.BigInteger(), nullable=False, server_default="0"
    ),
    sa.Column(
        "inline_conversion_converted",
        sa.BigInteger(),
        nullable=False,
        server_default="0",
    ),
    sa.Column(
        "inline_conversion_rejected",
        sa.BigInteger(),
        nullable=False,
        server_default="0",
    ),
    sa.Column(
        "inline_conversion_skipped", sa.BigInteger(), nullable=False, server_default="0"
    ),
    sa.Column(
        "inline_conversion_completed_at", sa.DateTime(timezone=True), nullable=True
    ),
    sa.Column("inline_conversion_ready_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    storage = op.get_bind().scalar(
        sa.text(
            "SELECT attstorage::text FROM pg_attribute "
            "WHERE attrelid = 'inline_content_payloads'::regclass "
            "AND attname = 'payload'"
        )
    )
    if storage != "e":
        op.execute(
            "ALTER TABLE inline_content_payloads "
            "ALTER COLUMN payload SET STORAGE EXTERNAL"
        )
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "object_content_reconciliation_state"
        )
    }
    for column in _PROGRESS_COLUMNS:
        if column.name not in existing:
            op.add_column("object_content_reconciliation_state", column)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for column in reversed(_PROGRESS_COLUMNS):
        op.drop_column("object_content_reconciliation_state", column.name)
    op.execute(
        "ALTER TABLE inline_content_payloads ALTER COLUMN payload SET STORAGE EXTENDED"
    )
