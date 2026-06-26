"""add AI builder tables

Create builder_sessions and builder_plans tables for the AI flow builder.

Revision ID: 202603121400
Revises: 579199d395dd
Create Date: 2026-03-12 14:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic
revision = "202603121400"
down_revision = "579199d395dd"
branch_labels = None
depends_on = None

# Valid status values
BUILDER_SESSION_STATUS_VALUES = (
    "chatting",
    "awaiting_approval",
    "applying",
    "applied",
    "cancelled",
)
BUILDER_PLAN_STATUS_VALUES = (
    "proposed",
    "approved",
    "applied",
    "rejected",
    "superseded",
)
BUILDER_TARGET_KIND_VALUES = ("create", "edit")


def upgrade() -> None:
    op.create_table(
        "builder_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="NULL for create sessions, set for edit sessions.",
        ),
        sa.Column(
            "target_kind",
            sa.String(16),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="chatting",
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "conversation",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="Rolling conversation history as JSON array.",
        ),
        sa.Column(
            "latest_plan_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"target_kind IN ({','.join(repr(v) for v in BUILDER_TARGET_KIND_VALUES)})",
            name="ck_builder_sessions_target_kind",
        ),
        sa.CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_SESSION_STATUS_VALUES)})",
            name="ck_builder_sessions_status",
        ),
    )

    op.create_index(
        "ix_builder_sessions_tenant_id",
        "builder_sessions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_builder_sessions_flow_id",
        "builder_sessions",
        ["flow_id"],
    )
    op.create_index(
        "ix_builder_sessions_actor_user_id",
        "builder_sessions",
        ["actor_user_id"],
    )

    op.create_table(
        "builder_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="proposed",
        ),
        sa.Column(
            "proposal_json",
            postgresql.JSONB(),
            nullable=False,
            comment="Serialized FlowBuilderProposal.",
        ),
        sa.Column(
            "spec_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hash of the spec for integrity verification.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["builder_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_PLAN_STATUS_VALUES)})",
            name="ck_builder_plans_status",
        ),
    )

    op.create_index(
        "ix_builder_plans_session_id",
        "builder_plans",
        ["session_id"],
    )
    op.create_index(
        "ix_builder_plans_tenant_id",
        "builder_plans",
        ["tenant_id"],
    )

    op.create_foreign_key(
        "fk_builder_sessions_latest_plan",
        "builder_sessions",
        "builder_plans",
        ["latest_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_builder_sessions_latest_plan", "builder_sessions", type_="foreignkey")
    op.drop_table("builder_plans")
    op.drop_table("builder_sessions")
