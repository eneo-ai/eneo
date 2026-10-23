"""Rerank models catalog

Rerank models become a catalog model type next to completion, embedding,
transcription and image: ``rerank_models`` carries tenant/provider ownership,
enablement, default, security classification and soft delete.

``assistants.rerank_model_id`` is the per-assistant choice, nullable and
``ON DELETE SET NULL`` so a reranker can be removed while assistants point at
it and they fall back to vector order. The retrieval step that reads it and
the editor that writes it follow in later tasks (#1035); the column lands
here to keep the feature to one migration.

Revision ID: 202610141000
Revises: 202610131800
Create Date: 2026-10-14

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610141000"
down_revision = "202610131800"
branch_labels = None
depends_on = None

# Stand-in for NULL tenant/provider ids in the display-name uniqueness scope,
# same as 20260602_unique_model_display_names.
SENTINEL = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.create_table(
        "rerank_models",
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
            name="ck_rerank_models_tenant_provider",
        ),
    )
    op.create_index("ix_rerank_models_tenant_id", "rerank_models", ["tenant_id"])
    op.create_index("ix_rerank_models_provider_id", "rerank_models", ["provider_id"])
    op.create_index("ix_rerank_models_deleted_at", "rerank_models", ["deleted_at"])
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_rerank_models_active_nickname
        ON rerank_models (
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
        "assistants",
        sa.Column("rerank_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistants_rerank_model_id_rerank_models",
        "assistants",
        "rerank_models",
        ["rerank_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_assistants_rerank_model_id", "assistants", ["rerank_model_id"])


def downgrade() -> None:
    op.drop_index("ix_assistants_rerank_model_id", table_name="assistants")
    op.drop_constraint(
        "fk_assistants_rerank_model_id_rerank_models",
        "assistants",
        type_="foreignkey",
    )
    op.drop_column("assistants", "rerank_model_id")

    op.execute("DROP INDEX IF EXISTS uq_rerank_models_active_nickname")
    op.drop_index("ix_rerank_models_deleted_at", table_name="rerank_models")
    op.drop_index("ix_rerank_models_provider_id", table_name="rerank_models")
    op.drop_index("ix_rerank_models_tenant_id", table_name="rerank_models")
    op.drop_table("rerank_models")
