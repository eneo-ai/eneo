"""Drop the declared operations of native transcription-service connections.

A transcription model always writes the text; a connected service is used only
to identify speakers, so a connection no longer declares what it does.
Downgrading restores the column with every kept connection as a speaker
service.

Revision ID: 202610090800
Revises: 202610082100
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610090800"
down_revision = "202610082100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_transcription_service_connections_operations",
        "transcription_service_connections",
        type_="check",
    )
    op.drop_column("transcription_service_connections", "operations")


def downgrade() -> None:
    op.add_column(
        "transcription_service_connections",
        sa.Column(
            "operations",
            postgresql.ARRAY(sa.String(16)),
            server_default=sa.text("'{diarize}'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_transcription_service_connections_operations",
        "transcription_service_connections",
        "cardinality(operations) >= 1 "
        "AND operations <@ ARRAY['transcribe', 'diarize']::varchar[]",
    )
