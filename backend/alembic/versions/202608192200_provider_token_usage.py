"""Add central provider token usage ledger.

Revision ID: 202608192200
Revises: 202608191530
Create Date: 2026-08-19 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608192200"
down_revision: str | None = "202608191530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_token_usages",
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "principal_service_id",
            sa.UUID(),
            sa.ForeignKey("service_principals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "completion_model_id",
            sa.UUID(),
            sa.ForeignKey("completion_models.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(source_type) > 0",
            name="ck_provider_token_usages_source_type_nonempty",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_provider_token_usages_input_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_provider_token_usages_output_nonnegative",
        ),
        sa.CheckConstraint(
            "num_nonnulls(principal_user_id, principal_service_id) = 1",
            name="ck_provider_token_usages_principal_identity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_provider_token_usages_source",
        ),
    )
    op.create_index(
        "ix_provider_token_usages_tenant_occurred",
        "provider_token_usages",
        ["tenant_id", "occurred_at"],
    )
    op.create_index(
        "ix_provider_token_usages_completion_model_id",
        "provider_token_usages",
        ["completion_model_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_token_usages_completion_model_id",
        table_name="provider_token_usages",
    )
    op.drop_index(
        "ix_provider_token_usages_tenant_occurred",
        table_name="provider_token_usages",
    )
    op.drop_table("provider_token_usages")
