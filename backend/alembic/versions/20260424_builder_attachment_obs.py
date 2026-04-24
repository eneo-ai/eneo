"""add builder_attachment_observations cache table

Revision ID: 20260424_builder_attachment_obs
Revises: 20260423_builder_planning_state
Create Date: 2026-04-24 00:00:00.000000

Tenant-scoped content-addressed cache for AI Builder attachment
observations (structured planning evidence per novel upload).

Cache key: (tenant_id, content_sha256, digest_version, fcm_version,
pattern_registry_version). A bump to any version stamp invalidates
prior rows so cached observations never cross a prompt-surface,
capability-surface, or pattern-surface change.

Eviction: per-tenant LRU keyed on last_accessed_at; the
(tenant_id, last_accessed_at) index keeps scans bounded per tenant.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260424_builder_attachment_obs"
down_revision = "20260423_builder_planning_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "builder_attachment_observations",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("digest_version", sa.Integer, nullable=False),
        sa.Column("fcm_version", sa.Integer, nullable=False),
        sa.Column("pattern_registry_version", sa.Integer, nullable=False),
        sa.Column("observation_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "deterministic_signals_json", postgresql.JSONB, nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "content_sha256",
            "digest_version",
            "fcm_version",
            "pattern_registry_version",
            name="pk_builder_attachment_observations",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64",
            name="ck_builder_attachment_obs_sha256_length",
        ),
        sa.CheckConstraint(
            "digest_version > 0",
            name="ck_builder_attachment_obs_digest_version",
        ),
        sa.CheckConstraint(
            "fcm_version > 0",
            name="ck_builder_attachment_obs_fcm_version",
        ),
        sa.CheckConstraint(
            "pattern_registry_version > 0",
            name="ck_builder_attachment_obs_pattern_registry_version",
        ),
    )
    op.create_index(
        "ix_builder_attachment_obs_tenant_last_accessed",
        "builder_attachment_observations",
        ["tenant_id", "last_accessed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_builder_attachment_obs_tenant_last_accessed",
        table_name="builder_attachment_observations",
    )
    op.drop_table("builder_attachment_observations")
