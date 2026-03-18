"""add_ai_builder_and_completion_model_token_fields

Add draft_revision counter to flows table, and create
builder_sessions + builder_plans tables for the AI flow builder.
Also add max_input_tokens and max_output_tokens to completion_models.

Revision ID: 202603121400
Revises: 202603091335
Create Date: 2026-03-12 14:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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


def _lookup_model_cost_defaults(litellm_module, *model_names: str | None):
    def _build(info):
        return (
            info.get("max_input_tokens"),
            info.get("max_output_tokens"),
        )

    for model_name in model_names:
        if not model_name:
            continue
        info = litellm_module.model_cost.get(model_name)
        if info is not None:
            return _build(info)

    prefixes = {
        key.split("/", 1)[0]
        for key in litellm_module.model_cost
        if "/" in key
    }
    for model_name in model_names:
        if not model_name or "/" in model_name:
            continue
        for prefix in sorted(prefixes):
            info = litellm_module.model_cost.get(f"{prefix}/{model_name}")
            if info is not None:
                return _build(info)

    return (None, None)


def upgrade() -> None:
    # 1. Add completion-model token fields and backfill from LiteLLM metadata.
    op.add_column(
        "completion_models",
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "completion_models",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
    )

    try:
        import litellm

        conn = op.get_bind()
        rows = conn.execute(
            sa.text(
                "SELECT id, name, litellm_model_name, token_limit "
                "FROM completion_models"
            )
        ).fetchall()

        for row in rows:
            max_input = None
            max_output = None

            candidate_input, candidate_output = _lookup_model_cost_defaults(
                litellm, row.litellm_model_name, row.name
            )
            if isinstance(candidate_input, int):
                max_input = candidate_input
            if isinstance(candidate_output, int):
                max_output = candidate_output

            if max_input is None:
                max_input = row.token_limit
            if max_output is None:
                continue

            conn.execute(
                sa.text(
                    "UPDATE completion_models "
                    "SET max_input_tokens = :max_input, max_output_tokens = :max_output "
                    "WHERE id = :id"
                ),
                {
                    "max_input": max_input,
                    "max_output": max_output,
                    "id": row.id,
                },
            )
    except ImportError:
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "UPDATE completion_models "
                "SET max_input_tokens = token_limit "
                "WHERE max_input_tokens IS NULL"
            )
        )

    # 2. Add draft_revision counter to flows table
    op.add_column(
        "flows",
        sa.Column(
            "draft_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Monotonic counter incremented on every draft mutation. Used for optimistic locking.",
        ),
    )

    # 3. Create builder_sessions table
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

    # 4. Create builder_plans table
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
            "spec_json",
            postgresql.JSONB(),
            nullable=False,
            comment="Serialized FlowDraftSpecCore.",
        ),
        sa.Column(
            "spec_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hash of the spec for integrity verification.",
        ),
        sa.Column(
            "envelope_json",
            postgresql.JSONB(),
            nullable=False,
            comment="Full PlannerPlanEnvelope including assumptions, lint warnings.",
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

    # Add FK from builder_sessions.latest_plan_id to builder_plans.id
    # (deferred since builder_plans didn't exist when builder_sessions was created)
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
    op.drop_column("flows", "draft_revision")
    op.drop_column("completion_models", "max_output_tokens")
    op.drop_column("completion_models", "max_input_tokens")
