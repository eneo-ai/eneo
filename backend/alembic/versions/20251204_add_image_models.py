"""add image_models tables for image generation

Revision ID: 20251204_add_image_models
Revises: 20251127_add_icons
Create Date: 2025-12-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic
revision = "20251204_add_image_models"
down_revision = "20251127_add_icons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create image_models table
    op.create_table(
        "image_models",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
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
        # Sync key - must match ai_models.yml
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("nickname", sa.String, nullable=False),
        # Provider info
        sa.Column("family", sa.String, nullable=False),
        sa.Column("stability", sa.String, nullable=False),
        sa.Column("hosting", sa.String, nullable=False),
        sa.Column("org", sa.String, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        # Model metadata
        sa.Column("open_source", sa.Boolean, nullable=True),
        sa.Column("is_deprecated", sa.Boolean, server_default="false", nullable=False),
        sa.Column("hf_link", sa.String, nullable=True),
        # Image-specific capabilities
        sa.Column("max_resolution", sa.String, nullable=True),
        sa.Column("supported_sizes", ARRAY(sa.String), nullable=True),
        sa.Column("supported_qualities", ARRAY(sa.String), nullable=True),
        sa.Column("max_images_per_request", sa.Integer, server_default="4", nullable=False),
        # Provider configuration
        sa.Column("litellm_model_name", sa.String, nullable=True),
        sa.Column("base_url", sa.String, nullable=True),
    )

    # Create image_model_settings table (per-tenant settings)
    op.create_table(
        "image_model_settings",
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
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "image_model_id",
            UUID(as_uuid=True),
            sa.ForeignKey("image_models.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_org_enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_org_default", sa.Boolean, server_default="false", nullable=False),
        sa.Column(
            "security_classification_id",
            UUID(as_uuid=True),
            sa.ForeignKey("security_classifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Create generated_images table (for history/analytics)
    op.create_table(
        "generated_images",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
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
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "image_model_id",
            UUID(as_uuid=True),
            sa.ForeignKey("image_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Generation parameters
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("revised_prompt", sa.Text, nullable=True),
        sa.Column("size", sa.String, nullable=True),
        sa.Column("quality", sa.String, nullable=True),
        # Image data
        sa.Column("blob", BYTEA, nullable=False),
        sa.Column("mimetype", sa.String, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        # Additional metadata
        sa.Column("metadata", JSONB, nullable=True),
    )

    # Create indexes for generated_images
    op.create_index(
        "idx_generated_images_tenant",
        "generated_images",
        ["tenant_id"],
    )
    op.create_index(
        "idx_generated_images_created",
        "generated_images",
        ["created_at"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_generated_images_created", table_name="generated_images")
    op.drop_index("idx_generated_images_tenant", table_name="generated_images")

    # Drop tables in reverse order
    op.drop_table("generated_images")
    op.drop_table("image_model_settings")
    op.drop_table("image_models")
