"""Image models catalog and built-in capability providers

Image generation models become a catalog model type next to completion,
embedding and transcription: ``image_models`` carries tenant/provider
ownership, enablement, default, security classification, per-image cost and
the default size/quality the image tool uses.

A built-in capability provider is an ``mcp_servers`` row whose endpoint is
one of Eneo's own loopback MCP servers (http_auth_type = "internal"). It
references the catalog image model it runs on through ``image_model_id`` and
carries no security classification of its own: the model's classification
applies at ask time.

Revision ID: 202607101007
Revises: 202607101006
Create Date: 2026-09-04

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101007"
down_revision = "202607101006"
branch_labels = None
depends_on = None

# Stand-in for NULL tenant/provider ids in the display-name uniqueness scope,
# same as 20260602_unique_model_display_names.
SENTINEL = "00000000-0000-0000-0000-000000000000"

MODEL_CONSTRAINT = "ck_mcp_servers_internal_image_model"
CLASSIFICATION_CONSTRAINT = "ck_mcp_servers_internal_no_classification"


def upgrade() -> None:
    op.create_table(
        "image_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("nickname", sa.String(), nullable=False),
        sa.Column("open_source", sa.Boolean(), nullable=True),
        sa.Column(
            "is_deprecated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("hf_link", sa.String(), nullable=True),
        sa.Column("family", sa.String(), nullable=False),
        sa.Column("stability", sa.String(), nullable=False),
        sa.Column("hosting", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("org", sa.String(), nullable=True),
        sa.Column("cost_per_image", sa.Numeric(20, 6), nullable=True),
        sa.Column("default_size", sa.String(), server_default="auto", nullable=False),
        sa.Column(
            "default_quality", sa.String(), server_default="auto", nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "security_classification_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["model_providers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["security_classification_id"],
            ["security_classifications.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(tenant_id IS NULL AND provider_id IS NULL) "
            "OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
            name="ck_image_models_tenant_provider",
        ),
    )
    op.create_index("ix_image_models_tenant_id", "image_models", ["tenant_id"])
    op.create_index("ix_image_models_provider_id", "image_models", ["provider_id"])
    op.create_index("ix_image_models_deleted_at", "image_models", ["deleted_at"])
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_image_models_active_nickname
        ON image_models (
            COALESCE(tenant_id, '{SENTINEL}'::uuid),
            COALESCE(provider_id, '{SENTINEL}'::uuid),
            lower(nickname)
        )
        WHERE deleted_at IS NULL
          AND is_deprecated = false
          AND nickname IS NOT NULL
        """
    )

    op.add_column(
        "mcp_servers",
        sa.Column("image_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_mcp_servers_image_model_id_image_models",
        "mcp_servers",
        "image_models",
        ["image_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_mcp_servers_image_model_id", "mcp_servers", ["image_model_id"])
    op.create_check_constraint(
        MODEL_CONSTRAINT,
        "mcp_servers",
        "(http_auth_type = 'internal') = (image_model_id IS NOT NULL)",
    )
    op.create_check_constraint(
        CLASSIFICATION_CONSTRAINT,
        "mcp_servers",
        "http_auth_type <> 'internal' OR security_classification_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(CLASSIFICATION_CONSTRAINT, "mcp_servers", type_="check")
    op.drop_constraint(MODEL_CONSTRAINT, "mcp_servers", type_="check")
    op.drop_index("ix_mcp_servers_image_model_id", table_name="mcp_servers")
    op.drop_constraint(
        "fk_mcp_servers_image_model_id_image_models",
        "mcp_servers",
        type_="foreignkey",
    )
    op.drop_column("mcp_servers", "image_model_id")

    op.execute("DROP INDEX IF EXISTS uq_image_models_active_nickname")
    op.drop_index("ix_image_models_deleted_at", table_name="image_models")
    op.drop_index("ix_image_models_provider_id", table_name="image_models")
    op.drop_index("ix_image_models_tenant_id", table_name="image_models")
    op.drop_table("image_models")
