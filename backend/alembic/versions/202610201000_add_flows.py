"""add flows

Flows core: flows, versions, files, runs, run files, step results, step
attempts, review checkpoints, transcript corrections; the hidden authoring
assistant's purpose column; the flows role permission.

Revision ID: 202610201000
Revises: 202610191000
Create Date: 2026-10-20 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "202610201000"
down_revision: str | None = "202610191000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def _fk(name: str, target: str, *, ondelete: str, nullable: bool) -> sa.Column:
    return sa.Column(
        name,
        UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=True)


def upgrade() -> None:
    op.create_table(
        "flows",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        _ts("deleted_at"),
        _fk("tenant_id", "tenants.id", ondelete="CASCADE", nullable=False),
        _fk("space_id", "spaces.id", ondelete="CASCADE", nullable=False),
        _fk("user_id", "users.id", ondelete="SET NULL", nullable=True),
        _fk("conversation_id", "sessions.id", ondelete="SET NULL", nullable=True),
    )
    op.create_index("ix_flows_tenant_space", "flows", ["tenant_id", "space_id"])

    op.create_table(
        "flow_versions",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        _fk("flow_id", "flows.id", ondelete="CASCADE", nullable=False),
        _fk("published_by_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )

    op.create_table(
        "flow_files",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("principal_type", sa.String(), nullable=False, server_default="user"),
        _fk("principal_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.Column("principal_service_id", UUID(as_uuid=True), nullable=True),
        _fk("flow_id", "flows.id", ondelete="CASCADE", nullable=False),
        _fk("file_id", "files.id", ondelete="CASCADE", nullable=False),
        sa.UniqueConstraint(
            "flow_id", "file_id", "role", name="uq_flow_files_flow_file_role"
        ),
    )

    op.create_table(
        "flow_runs",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("flow_version", sa.Integer(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False, server_default="user"),
        _fk("principal_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.Column("principal_service_id", UUID(as_uuid=True), nullable=True),
        _fk(
            "created_by_api_key_id",
            "api_keys_v2.id",
            ondelete="SET NULL",
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("run_label", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("input_payload_json", JSONB(), nullable=True),
        sa.Column("output_payload_json", JSONB(), nullable=True),
        sa.Column("error_json", JSONB(), nullable=True),
        _ts("started_at"),
        _ts("finished_at"),
        _ts("cancelled_at"),
        _ts("heartbeat_at"),
        _fk("tenant_id", "tenants.id", ondelete="CASCADE", nullable=False),
        _fk("flow_id", "flows.id", ondelete="CASCADE", nullable=False),
        _fk("job_id", "jobs.id", ondelete="SET NULL", nullable=True),
        sa.UniqueConstraint(
            "flow_id", "idempotency_key", name="uq_flow_runs_flow_idempotency_key"
        ),
    )
    op.create_index("ix_flow_runs_flow_created", "flow_runs", ["flow_id", "created_at"])
    op.create_index(
        "ix_flow_runs_running",
        "flow_runs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "flow_run_files",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("field_key", sa.String(), nullable=True),
        sa.Column("step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        _fk("flow_run_id", "flow_runs.id", ondelete="CASCADE", nullable=False),
        _fk("file_id", "files.id", ondelete="CASCADE", nullable=False),
        sa.UniqueConstraint(
            "flow_run_id", "file_id", "role", name="uq_flow_run_files_run_file_role"
        ),
    )

    op.create_table(
        "flow_step_results",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "current_attempt_no", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("input_payload_json", JSONB(), nullable=True),
        sa.Column("output_payload_json", JSONB(), nullable=True),
        sa.Column("num_tokens_input", sa.Integer(), nullable=True),
        sa.Column("num_tokens_output", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        _ts("started_at"),
        _ts("finished_at"),
        _fk("flow_run_id", "flow_runs.id", ondelete="CASCADE", nullable=False),
        sa.UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_step_results_run_step"
        ),
    )

    op.create_table(
        "flow_step_attempts",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="started"),
        sa.Column("error_message", sa.String(), nullable=True),
        _ts("finished_at"),
        _fk("flow_run_id", "flow_runs.id", ondelete="CASCADE", nullable=False),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_attempts_run_step_attempt",
        ),
    )
    op.create_index(
        "ix_flow_step_attempts_run_started",
        "flow_step_attempts",
        ["flow_run_id"],
        postgresql_where=sa.text("status = 'started'"),
    )

    op.create_table(
        "flow_run_review_checkpoints",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "state", sa.String(), nullable=False, server_default="awaiting_review"
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_mode", sa.String(), nullable=False),
        sa.Column("output_type", sa.String(), nullable=False, server_default="text"),
        sa.Column("original_payload_json", JSONB(), nullable=True),
        sa.Column("current_payload_json", JSONB(), nullable=True),
        sa.Column(
            "requester_principal_type",
            sa.String(),
            nullable=False,
            server_default="user",
        ),
        _fk("requester_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.Column("requester_service_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_principal_type", sa.String(), nullable=True),
        _fk("decided_by_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.Column("decided_by_service_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        _ts("edited_at"),
        _ts("approved_at"),
        _ts("rejected_at"),
        _ts("resumed_at"),
        _ts("cancelled_at"),
        _ts("expires_at"),
        _fk("tenant_id", "tenants.id", ondelete="CASCADE", nullable=False),
        _fk("flow_id", "flows.id", ondelete="CASCADE", nullable=False),
        _fk("flow_run_id", "flow_runs.id", ondelete="CASCADE", nullable=False),
    )
    op.create_index(
        "uq_flow_run_review_checkpoints_one_active_per_run",
        "flow_run_review_checkpoints",
        ["flow_run_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('awaiting_review', 'edited', 'approved')"),
    )

    op.create_table(
        "flow_transcript_corrections",
        _id_column(),
        *_timestamp_columns(),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("segments_hash", sa.String(), nullable=False),
        sa.Column(
            "occurrences_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "speaker_edits_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("speaker_names", JSONB(), nullable=True),
        sa.Column(
            "edited_by_principal_type",
            sa.String(),
            nullable=False,
            server_default="user",
        ),
        _fk("edited_by_user_id", "users.id", ondelete="SET NULL", nullable=True),
        sa.Column("edited_by_service_id", UUID(as_uuid=True), nullable=True),
        _fk("tenant_id", "tenants.id", ondelete="CASCADE", nullable=False),
        _fk("flow_id", "flows.id", ondelete="CASCADE", nullable=False),
        _fk("flow_run_id", "flow_runs.id", ondelete="CASCADE", nullable=False),
        sa.UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_transcript_corrections_run_step"
        ),
    )

    # The hidden per-space authoring assistant is an ordinary assistant row
    # whose purpose names what it is for; listings exclude rows with a purpose.
    op.add_column("assistants", sa.Column("purpose", sa.String(), nullable=True))
    op.create_index(
        "uq_assistants_flows_purpose_per_space",
        "assistants",
        ["space_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'flows'"),
    )

    # Roles that may build apps may build flows, so the feature does not
    # silently disappear for existing deployments.
    op.execute(
        sa.text(
            """
            UPDATE roles
            SET permissions = array_append(permissions, 'flows')
            WHERE 'apps' = ANY(permissions)
              AND NOT ('flows' = ANY(permissions))
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE roles SET permissions = array_remove(permissions, 'flows')")
    )
    op.drop_index("uq_assistants_flows_purpose_per_space", table_name="assistants")
    op.drop_column("assistants", "purpose")
    op.drop_table("flow_transcript_corrections")
    op.drop_index(
        "uq_flow_run_review_checkpoints_one_active_per_run",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_table("flow_run_review_checkpoints")
    op.drop_index("ix_flow_step_attempts_run_started", table_name="flow_step_attempts")
    op.drop_table("flow_step_attempts")
    op.drop_table("flow_step_results")
    op.drop_table("flow_run_files")
    op.drop_index("ix_flow_runs_running", table_name="flow_runs")
    op.drop_index("ix_flow_runs_flow_created", table_name="flow_runs")
    op.drop_table("flow_runs")
    op.drop_table("flow_files")
    op.drop_table("flow_versions")
    op.drop_index("ix_flows_tenant_space", table_name="flows")
    op.drop_table("flows")
