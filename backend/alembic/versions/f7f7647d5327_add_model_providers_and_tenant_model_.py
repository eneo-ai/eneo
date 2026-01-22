"""add_model_providers_and_tenant_model_columns
Revision ID: f7f7647d5327
Revises: d8103542e81d
Create Date: 2025-11-21 10:08:15.953899
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = 'f7f7647d5327'
down_revision = 'e23b168d0080'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create model_providers table
    op.create_table(
        "model_providers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("credentials", postgresql.JSONB(), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_model_providers_tenant_name"),
    )
    op.create_index("idx_model_providers_tenant_id", "model_providers", ["tenant_id"])

    # Add tenant_id and provider_id columns to completion_models
    op.add_column("completion_models", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.add_column("completion_models", sa.Column("provider_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_completion_models_tenant_id",
        "completion_models",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_completion_models_provider_id",
        "completion_models",
        "model_providers",
        ["provider_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_completion_models_tenant_id", "completion_models", ["tenant_id"])
    op.create_index("idx_completion_models_provider_id", "completion_models", ["provider_id"])
    # Check constraint: both NULL (global) OR both NOT NULL (tenant)
    op.create_check_constraint(
        "ck_completion_models_tenant_provider",
        "completion_models",
        "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
    )

    # Add tenant_id and provider_id columns to embedding_models
    op.add_column("embedding_models", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.add_column("embedding_models", sa.Column("provider_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_embedding_models_tenant_id",
        "embedding_models",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_embedding_models_provider_id",
        "embedding_models",
        "model_providers",
        ["provider_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_embedding_models_tenant_id", "embedding_models", ["tenant_id"])
    op.create_index("idx_embedding_models_provider_id", "embedding_models", ["provider_id"])
    op.create_check_constraint(
        "ck_embedding_models_tenant_provider",
        "embedding_models",
        "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
    )

    # Add tenant_id and provider_id columns to transcription_models
    op.add_column("transcription_models", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.add_column("transcription_models", sa.Column("provider_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_transcription_models_tenant_id",
        "transcription_models",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_transcription_models_provider_id",
        "transcription_models",
        "model_providers",
        ["provider_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_transcription_models_tenant_id", "transcription_models", ["tenant_id"])
    op.create_index("idx_transcription_models_provider_id", "transcription_models", ["provider_id"])
    op.create_check_constraint(
        "ck_transcription_models_tenant_provider",
        "transcription_models",
        "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Remove check constraints from model tables
    op.drop_constraint("ck_transcription_models_tenant_provider", "transcription_models", type_="check")
    op.drop_constraint("ck_embedding_models_tenant_provider", "embedding_models", type_="check")
    op.drop_constraint("ck_completion_models_tenant_provider", "completion_models", type_="check")

    # Remove columns from transcription_models
    op.drop_index("idx_transcription_models_provider_id", table_name="transcription_models")
    op.drop_index("idx_transcription_models_tenant_id", table_name="transcription_models")
    op.drop_constraint("fk_transcription_models_provider_id", "transcription_models", type_="foreignkey")
    op.drop_constraint("fk_transcription_models_tenant_id", "transcription_models", type_="foreignkey")
    op.drop_column("transcription_models", "provider_id")
    op.drop_column("transcription_models", "tenant_id")

    # Remove columns from embedding_models
    op.drop_index("idx_embedding_models_provider_id", table_name="embedding_models")
    op.drop_index("idx_embedding_models_tenant_id", table_name="embedding_models")
    op.drop_constraint("fk_embedding_models_provider_id", "embedding_models", type_="foreignkey")
    op.drop_constraint("fk_embedding_models_tenant_id", "embedding_models", type_="foreignkey")
    op.drop_column("embedding_models", "provider_id")
    op.drop_column("embedding_models", "tenant_id")

    # Remove columns from completion_models
    op.drop_index("idx_completion_models_provider_id", table_name="completion_models")
    op.drop_index("idx_completion_models_tenant_id", table_name="completion_models")
    op.drop_constraint("fk_completion_models_provider_id", "completion_models", type_="foreignkey")
    op.drop_constraint("fk_completion_models_tenant_id", "completion_models", type_="foreignkey")
    op.drop_column("completion_models", "provider_id")
    op.drop_column("completion_models", "tenant_id")

    # Drop model_providers table
    op.drop_index("idx_model_providers_tenant_id", table_name="model_providers")
    op.drop_table("model_providers")
