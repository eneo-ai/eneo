"""Create the final Flow AI Builder schema.

Revision ID: 202608201200
Revises: 202608201100
Create Date: 2026-08-20 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608201200"
down_revision = "202608201100"
branch_labels = None
depends_on = None


def _replace_resource_binding_source_constraint(*, include_builder: bool) -> None:
    op.drop_constraint(
        "ck_flow_resource_bindings_source",
        "flow_resource_bindings",
        type_="check",
    )
    values = (
        "'ai_builder','package_import','manual_admin'"
        if include_builder
        else "'package_import','manual_admin'"
    )
    op.create_check_constraint(
        "ck_flow_resource_bindings_source",
        "flow_resource_bindings",
        f"source IN ({values})",
        postgresql_not_valid=True,
    )
    op.execute(
        "ALTER TABLE flow_resource_bindings "
        "VALIDATE CONSTRAINT ck_flow_resource_bindings_source"
    )


def _create_builder_sessions() -> None:
    op.create_table(
        "builder_sessions",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=True),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="chatting",
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "conversation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("active_request_id", sa.Uuid(), nullable=True),
        sa.Column("lock_token", sa.Uuid(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_plan_id", sa.Uuid(), nullable=True),
        sa.Column(
            "planning_state_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "planning_state_version",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("latest_turn_id", sa.Uuid(), nullable=True),
        sa.Column(
            "latest_turn_request_fingerprint", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "latest_turn_request_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("latest_turn_state", sa.String(length=32), nullable=True),
        sa.Column("latest_turn_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "latest_turn_error_jsonb",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.CheckConstraint(
            "latest_turn_error_jsonb IS NULL OR latest_turn_state = 'committed'",
            name="ck_builder_sessions_latest_turn_error_committed",
        ),
        sa.CheckConstraint(
            "latest_turn_state IS NULL OR latest_turn_state IN "
            "('open','processing','committed','failed_before_provider',"
            "'provider_outcome_unknown')",
            name="ck_builder_sessions_latest_turn_state",
        ),
        sa.CheckConstraint(
            "status IN ('chatting','awaiting_approval','applied','cancelled')",
            name="ck_builder_sessions_status",
        ),
        sa.CheckConstraint(
            "target_kind IN ('create','edit')",
            name="ck_builder_sessions_target_kind",
        ),
        sa.CheckConstraint(
            "(active_request_id IS NULL AND lock_token IS NULL "
            "AND locked_at IS NULL AND lock_expires_at IS NULL) OR "
            "(active_request_id IS NOT NULL AND lock_token IS NOT NULL "
            "AND locked_at IS NOT NULL AND lock_expires_at IS NOT NULL)",
            name="ck_builder_sessions_send_lock_all_or_none",
        ),
        sa.CheckConstraint(
            "(latest_turn_id IS NULL "
            "AND latest_turn_request_fingerprint IS NULL "
            "AND latest_turn_request_jsonb IS NULL "
            "AND latest_turn_state IS NULL "
            "AND latest_turn_message_id IS NULL "
            "AND latest_turn_error_jsonb IS NULL) OR "
            "(latest_turn_id IS NOT NULL "
            "AND latest_turn_request_fingerprint IS NOT NULL "
            "AND latest_turn_request_jsonb IS NOT NULL "
            "AND latest_turn_state IS NOT NULL "
            "AND latest_turn_message_id IS NOT NULL)",
            name="ck_builder_sessions_latest_turn_all_or_none",
        ),
        sa.CheckConstraint(
            "latest_turn_request_fingerprint IS NULL OR "
            "char_length(latest_turn_request_fingerprint) = 64",
            name="ck_builder_sessions_latest_turn_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_builder_sessions_flow_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_builder_sessions_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_builder_sessions_actor_user_id"),
        "builder_sessions",
        ["actor_user_id"],
    )
    op.create_index(
        op.f("ix_builder_sessions_flow_id"), "builder_sessions", ["flow_id"]
    )
    op.create_index(
        op.f("ix_builder_sessions_lock_expires_at"),
        "builder_sessions",
        ["lock_expires_at"],
    )
    op.create_index(
        op.f("ix_builder_sessions_space_id"), "builder_sessions", ["space_id"]
    )
    op.create_index(
        "ix_builder_sessions_tenant_actor_updated",
        "builder_sessions",
        ["tenant_id", "actor_user_id", "updated_at", "created_at"],
    )
    op.create_index(
        op.f("ix_builder_sessions_tenant_id"), "builder_sessions", ["tenant_id"]
    )


def _create_builder_plans() -> None:
    op.create_table(
        "builder_plans",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="proposed",
            nullable=False,
        ),
        sa.Column(
            "proposal_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Serialized FlowBuilderProposal.",
        ),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.CheckConstraint(
            "status IN ('proposed','approved','applied','superseded')",
            name="ck_builder_plans_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            name="fk_builder_plans_session_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["builder_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "session_id", name="uq_builder_plans_id_session_id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_builder_plans_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_builder_plans_session_id"), "builder_plans", ["session_id"]
    )
    op.create_index(op.f("ix_builder_plans_tenant_id"), "builder_plans", ["tenant_id"])
    op.create_foreign_key(
        "fk_builder_sessions_latest_plan_session",
        "builder_sessions",
        "builder_plans",
        ["latest_plan_id", "id"],
        ["id", "session_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def _create_builder_session_files() -> None:
    op.create_table(
        "builder_session_files",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
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
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            name="fk_builder_session_files_file_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            name="fk_builder_session_files_session_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["builder_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "file_id"),
    )
    op.create_index(
        "ix_builder_session_files_file_id",
        "builder_session_files",
        ["file_id"],
    )
    op.create_index(
        op.f("ix_builder_session_files_tenant_id"),
        "builder_session_files",
        ["tenant_id"],
    )


def upgrade() -> None:
    _replace_resource_binding_source_constraint(include_builder=True)
    _create_builder_sessions()
    _create_builder_plans()
    _create_builder_session_files()


def downgrade() -> None:
    op.drop_table("builder_session_files")
    op.drop_constraint(
        "fk_builder_sessions_latest_plan_session",
        "builder_sessions",
        type_="foreignkey",
    )
    op.drop_table("builder_plans")
    op.drop_table("builder_sessions")
    _replace_resource_binding_source_constraint(include_builder=False)
