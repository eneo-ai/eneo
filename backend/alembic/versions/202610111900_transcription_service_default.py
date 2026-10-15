"""Let an administrator mark one transcription service as the default.

A flow draft that asks for speaker labels without having chosen a service gets
the organisation's default stored as its own choice. No existing connection
becomes the default: it is marked, never inferred.

Revision ID: 202610111900
Revises: 202610091005
"""

import sqlalchemy as sa

from alembic import op

revision = "202610111900"
down_revision = "202610091005"
branch_labels = None
depends_on = None

_TABLE = "transcription_service_connections"
_INDEX = "uq_transcription_service_connections_default"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # At most one default per organisation.
    op.create_index(
        _INDEX,
        _TABLE,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, "is_default")
