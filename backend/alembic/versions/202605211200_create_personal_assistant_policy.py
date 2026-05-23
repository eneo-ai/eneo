"""create personal_assistant_policies + m2m tables

Tenant-level policy for personal assistant (default assistants in user-owned
spaces). Stores allowed completion models, MCP servers, and the default
prompt to enforce. Per-dimension *_enforced flags distinguish "no
restriction" from "deny-all" (empty whitelist).

ON DELETE RESTRICT on default_prompt_library_id prevents admins from
silently breaking 1000 chats by deleting a referenced prompt — the service
surfaces a 409 first.

Revision ID: 202605211200
Revises: 202605211100
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

revision = "202605211200"
down_revision = "202605211100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_assistant_policies",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "models_restriction_enabled",
            sa.Boolean(),
            server_default="False",
            nullable=False,
        ),
        sa.Column(
            "mcp_restriction_enabled",
            sa.Boolean(),
            server_default="False",
            nullable=False,
        ),
        sa.Column(
            "prompt_enforcement_enabled",
            sa.Boolean(),
            server_default="False",
            nullable=False,
        ),
        sa.Column("default_prompt_library_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["default_prompt_library_id"], ["prompt_library.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", name="uq_personal_assistant_policies_tenant_id"
        ),
        sa.CheckConstraint(
            "NOT prompt_enforcement_enabled OR default_prompt_library_id IS NOT NULL",
            name="prompt_enforcement_requires_prompt",
        ),
    )

    op.create_table(
        "personal_assistant_policy_completion_models",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("completion_model_id", sa.UUID(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default="False", nullable=False
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
        sa.ForeignKeyConstraint(
            ["policy_id"], ["personal_assistant_policies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["completion_model_id"], ["completion_models.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("policy_id", "completion_model_id"),
    )
    op.create_index(
        "uniq_policy_default_model",
        "personal_assistant_policy_completion_models",
        ["policy_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "personal_assistant_policy_mcp_servers",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("mcp_server_id", sa.UUID(), nullable=False),
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
            ["policy_id"], ["personal_assistant_policies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("policy_id", "mcp_server_id"),
    )


def downgrade() -> None:
    op.drop_table("personal_assistant_policy_mcp_servers")
    op.drop_index(
        "uniq_policy_default_model",
        table_name="personal_assistant_policy_completion_models",
    )
    op.drop_table("personal_assistant_policy_completion_models")
    op.drop_table("personal_assistant_policies")
