"""add governance_policy_providers join table

Allows admins to whitelist a whole provider (e.g. all Anthropic models)
in addition to individual completion models. The effective allowed-model
set is the union of explicitly-listed models and all org-enabled models
under the whitelisted providers — so new models added to a whitelisted
provider auto-inherit access until the admin removes the provider.

Revision ID: 202605221000
Revises: 202605211600
Create Date: 2026-05-22
"""

import sqlalchemy as sa

from alembic import op

revision = "202605221000"
down_revision = "202605211600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governance_policy_providers",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("model_provider_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["policy_id"], ["governance_policies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_provider_id"], ["model_providers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("policy_id", "model_provider_id"),
    )


def downgrade() -> None:
    op.drop_table("governance_policy_providers")
