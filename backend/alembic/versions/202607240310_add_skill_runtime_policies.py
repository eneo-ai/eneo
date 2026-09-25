"""add tenant Skill runtime policies

Revision ID: 202607240310
Revises: 202607240115
Create Date: 2026-07-24 03:10:00.000000
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607240310"
down_revision: str | None = "202607240115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_MAX_ATTACHED_SKILLS = 100
_MIN_MAX_ATTACHED_SKILLS = 1
_MAX_MAX_ATTACHED_SKILLS = 1000


def _seed_max_attached_skills() -> int:
    """The pre-policy limit lived in SKILL_MAX_BINDINGS; seeding from it keeps
    a deployment's effective limit unchanged when the stored policy takes
    over as the source of truth."""
    raw = os.environ.get("SKILL_MAX_BINDINGS", "")
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_ATTACHED_SKILLS
    return max(_MIN_MAX_ATTACHED_SKILLS, min(value, _MAX_MAX_ATTACHED_SKILLS))


def upgrade() -> None:
    op.create_table(
        "skill_runtime_policies",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("selective_activation_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_attached_skills", sa.Integer(), nullable=False),
        sa.Column("context_share_percent", sa.Integer(), nullable=False),
        sa.Column("max_activations_per_turn", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "max_attached_skills BETWEEN 1 AND 1000",
            name="ck_skill_runtime_policies_max_attached_skills",
        ),
        sa.CheckConstraint(
            "context_share_percent BETWEEN 1 AND 100",
            name="ck_skill_runtime_policies_context_share_percent",
        ),
        sa.CheckConstraint(
            "max_activations_per_turn BETWEEN 1 AND 10",
            name="ck_skill_runtime_policies_max_activations_per_turn",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_skill_runtime_policies_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_skill_runtime_policies"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO skill_runtime_policies (
                tenant_id,
                selective_activation_enabled,
                max_attached_skills,
                context_share_percent,
                max_activations_per_turn
            )
            SELECT id, false, :max_attached_skills, 10, 10
            FROM tenants
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ).bindparams(max_attached_skills=_seed_max_attached_skills())
    )


def downgrade() -> None:
    op.drop_table("skill_runtime_policies")
