"""transcription model migration lifecycle

Fas 4a of the model-table alignment: give transcription models the same in-app
migration feature completion models already have.

  - Add `migrated_to_model_id` (self-FK, RESTRICT) to transcription_models, the
    last lifecycle column missing for parity (deleted_at + nickname were added
    in Fas 1).
  - Create `transcription_model_migration_history`, mirroring
    `completion_model_migration_history` (final shape: SET NULL model FKs +
    from/to name + provider_type columns).

Revision ID: 20260603_transcription_migrate
Revises: 20260602_unique_display_names
Create Date: 2026-06-03

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic
revision = "20260603_transcription_migrate"
down_revision = "20260602_unique_display_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transcription_models",
        sa.Column("migrated_to_model_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_transcription_models_migrated_to",
        "transcription_models",
        "transcription_models",
        ["migrated_to_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_transcription_models_migrated_to_model_id",
        "transcription_models",
        ["migrated_to_model_id"],
    )

    op.create_table(
        "transcription_model_migration_history",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("migration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_model_id", UUID(as_uuid=True), nullable=True),
        sa.Column("to_model_id", UUID(as_uuid=True), nullable=True),
        sa.Column("from_model_name", sa.String(255), nullable=True),
        sa.Column("to_model_name", sa.String(255), nullable=True),
        sa.Column("from_provider_type", sa.String(255), nullable=True),
        sa.Column("to_provider_type", sa.String(255), nullable=True),
        sa.Column("initiated_by", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("entity_types", sa.JSON, nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("migrated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON, nullable=True),
        sa.Column("migration_details", sa.JSON, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["from_model_id"], ["transcription_models.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["to_model_id"], ["transcription_models.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("migration_id"),
    )
    op.create_index(
        "idx_tm_migration_history_tenant",
        "transcription_model_migration_history",
        ["tenant_id"],
    )
    op.create_index(
        "idx_tm_migration_history_from_model",
        "transcription_model_migration_history",
        ["from_model_id"],
    )
    op.create_index(
        "idx_tm_migration_history_to_model",
        "transcription_model_migration_history",
        ["to_model_id"],
    )
    op.create_index(
        "idx_tm_migration_history_status",
        "transcription_model_migration_history",
        ["status"],
    )
    op.create_index(
        "idx_tm_migration_history_migration_id",
        "transcription_model_migration_history",
        ["migration_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_tm_migration_history_migration_id",
        table_name="transcription_model_migration_history",
    )
    op.drop_index(
        "idx_tm_migration_history_status",
        table_name="transcription_model_migration_history",
    )
    op.drop_index(
        "idx_tm_migration_history_to_model",
        table_name="transcription_model_migration_history",
    )
    op.drop_index(
        "idx_tm_migration_history_from_model",
        table_name="transcription_model_migration_history",
    )
    op.drop_index(
        "idx_tm_migration_history_tenant",
        table_name="transcription_model_migration_history",
    )
    op.drop_table("transcription_model_migration_history")

    op.drop_index(
        "ix_transcription_models_migrated_to_model_id",
        table_name="transcription_models",
    )
    op.drop_constraint(
        "fk_transcription_models_migrated_to",
        "transcription_models",
        type_="foreignkey",
    )
    op.drop_column("transcription_models", "migrated_to_model_id")
