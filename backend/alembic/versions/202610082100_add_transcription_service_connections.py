"""Organisation-owned native transcription-service connections and space grants.

Additive: no existing row changes, and nothing reads the tables until an
administrator creates a connection. The deployment-wide
FLOW_TRANSCRIPTION_SERVICE_* settings are not imported: an organisation's
secret is entered by its own administrator.

Revision ID: 202610082100
Revises: 202610081100
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610082100"
down_revision = "202610081100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcription_service_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("endpoint_url", sa.String(2048), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("operations", postgresql.ARRAY(sa.String(16)), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "security_classification_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["security_classification_id"],
            ["security_classifications.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_transcription_service_connections_name"
        ),
        sa.CheckConstraint(
            "cardinality(operations) >= 1 "
            "AND operations <@ ARRAY['transcribe', 'diarize']::varchar[]",
            name="ck_transcription_service_connections_operations",
        ),
    )
    op.create_table(
        "spaces_transcription_service_connections",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("space_id", "connection_id"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["transcription_service_connections.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_spaces_transcription_service_connections_connection_id",
        "spaces_transcription_service_connections",
        ["connection_id"],
    )


def downgrade() -> None:
    op.drop_table("spaces_transcription_service_connections")
    op.drop_table("transcription_service_connections")
