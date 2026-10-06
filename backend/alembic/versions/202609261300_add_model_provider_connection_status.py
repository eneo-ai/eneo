"""Record model provider connection checks and an admin-entered key expiry.

Additive: four nullable columns on model_providers. Existing providers read
as never checked and without an expiry date.

Revision ID: 202609261300
Revises: 202609261200
"""

import sqlalchemy as sa

from alembic import op

revision = "202609261300"
down_revision = "202609261200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_providers", sa.Column("key_expires_on", sa.Date(), nullable=True)
    )
    op.add_column(
        "model_providers", sa.Column("connection_status", sa.String(), nullable=True)
    )
    op.add_column(
        "model_providers", sa.Column("connection_error", sa.String(), nullable=True)
    )
    op.add_column(
        "model_providers",
        sa.Column("connection_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # A status always comes with its time; a failure always with its reason.
    op.create_check_constraint(
        "ck_model_providers_connection_check",
        "model_providers",
        "(connection_status IS NULL AND connection_checked_at IS NULL"
        " AND connection_error IS NULL)"
        " OR (connection_status = 'ok' AND connection_checked_at IS NOT NULL"
        " AND connection_error IS NULL)"
        " OR (connection_status = 'failed' AND connection_checked_at IS NOT NULL"
        " AND connection_error IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_providers_connection_check", "model_providers", type_="check"
    )
    op.drop_column("model_providers", "connection_checked_at")
    op.drop_column("model_providers", "connection_error")
    op.drop_column("model_providers", "connection_status")
    op.drop_column("model_providers", "key_expires_on")
