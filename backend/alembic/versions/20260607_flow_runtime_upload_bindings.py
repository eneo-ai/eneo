"""bind Flow runtime uploads before step-input attachment

Runtime uploads are Flow-owned input candidates before they become
run-attempt attachments. The binding table preserves that provenance while
`flow_run_step_input_files` remains the canonical attached-input owner.

Revision ID: 20260607_flow_runtime_uploads
Revises: 20260607_step_input_attempt
Create Date: 2026-06-07 21:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260607_flow_runtime_uploads"
down_revision = "20260607_step_input_attempt"
branch_labels = None
depends_on = None

_RUNTIME_UPLOADS_TABLE = "flow_runtime_uploaded_files"
_STEP_INPUT_FILES_TABLE = "flow_run_step_input_files"
_STEP_INPUT_RUNTIME_UPLOAD_FK = "fk_flow_run_step_input_files_runtime_upload"


def _ambiguous_attached_runtime_file_count() -> int:
    bind = op.get_bind()
    return int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM (
                    SELECT file_id
                    FROM flow_run_step_input_files
                    GROUP BY file_id
                    HAVING count(DISTINCT flow_id) > 1
                        OR count(DISTINCT tenant_id) > 1
                ) AS ambiguous_files
                """
            )
        )
        or 0
    )


def _ambiguous_attached_runtime_file_samples() -> list[str]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                file_id::text,
                array_agg(DISTINCT flow_id::text ORDER BY flow_id::text),
                array_agg(DISTINCT tenant_id::text ORDER BY tenant_id::text)
            FROM flow_run_step_input_files
            GROUP BY file_id
            HAVING count(DISTINCT flow_id) > 1
                OR count(DISTINCT tenant_id) > 1
            ORDER BY file_id
            LIMIT 5
            """
        )
    )
    return [
        f"file_id={row[0]} flow_ids={row[1]} tenant_ids={row[2]}" for row in rows
    ]


def _backfill_existing_attached_runtime_uploads() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO flow_runtime_uploaded_files (
                created_at,
                updated_at,
                file_id,
                flow_id,
                tenant_id,
                uploaded_for_step_id,
                owner_type,
                owner_user_id,
                owner_service_id
            )
            SELECT DISTINCT ON (step_input.file_id)
                step_input.created_at,
                step_input.updated_at,
                step_input.file_id,
                step_input.flow_id,
                step_input.tenant_id,
                step_input.step_id,
                files.owner_type,
                files.owner_user_id,
                files.owner_service_id
            FROM flow_run_step_input_files AS step_input
            JOIN files ON files.id = step_input.file_id
            ORDER BY
                step_input.file_id,
                step_input.created_at,
                step_input.step_order,
                step_input.ordinal
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        _RUNTIME_UPLOADS_TABLE,
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "uploaded_for_step_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Runtime step id accepted by the published Flow definition.",
        ),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "owner_type IN ('user','service_key')",
            name=op.f("ck_flow_runtime_uploaded_files_owner_type"),
        ),
        sa.CheckConstraint(
            "("
            "owner_type = 'user' "
            "AND owner_user_id IS NOT NULL "
            "AND owner_service_id IS NULL"
            ") OR ("
            "owner_type = 'service_key' "
            "AND owner_user_id IS NULL "
            "AND owner_service_id IS NOT NULL"
            ")",
            name=op.f("ck_flow_runtime_uploaded_files_owner_identity"),
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_flow_runtime_uploaded_files_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_flow_runtime_uploaded_files_flow_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_service_id"],
            ["service_principals.id"],
            name=op.f(
                "fk_flow_runtime_uploaded_files_owner_service_id_service_principals"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_flow_runtime_uploaded_files_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_runtime_uploaded_files_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_flow_runtime_uploaded_files")),
        sa.UniqueConstraint(
            "file_id",
            "flow_id",
            "tenant_id",
            name="uq_flow_runtime_uploaded_files_file_flow_tenant",
        ),
    )
    op.create_index(
        op.f("ix_flow_runtime_uploaded_files_flow_id"),
        _RUNTIME_UPLOADS_TABLE,
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_runtime_uploaded_files_service_owner",
        _RUNTIME_UPLOADS_TABLE,
        ["tenant_id", "flow_id", "owner_service_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("owner_type = 'service_key'"),
    )
    op.create_index(
        op.f("ix_flow_runtime_uploaded_files_tenant_id"),
        _RUNTIME_UPLOADS_TABLE,
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_runtime_uploaded_files_user_owner",
        _RUNTIME_UPLOADS_TABLE,
        ["tenant_id", "flow_id", "owner_user_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("owner_type = 'user'"),
    )

    ambiguous_count = _ambiguous_attached_runtime_file_count()
    if ambiguous_count > 0:
        samples = "; ".join(_ambiguous_attached_runtime_file_samples())
        raise RuntimeError(
            f"Cannot backfill {_RUNTIME_UPLOADS_TABLE}: {ambiguous_count} "
            "existing runtime input file ids are attached to multiple flows or "
            f"tenants. Sample files: {samples}. Re-upload those files per Flow "
            "or delete the ambiguous test data, then rerun the upgrade."
        )

    # Pre-existing attached step-input files become runtime-upload provenance rows.
    _backfill_existing_attached_runtime_uploads()

    # Backfilled rows satisfy the FK; NOT VALID keeps the add brief before validation.
    op.create_foreign_key(
        _STEP_INPUT_RUNTIME_UPLOAD_FK,
        _STEP_INPUT_FILES_TABLE,
        _RUNTIME_UPLOADS_TABLE,
        ["file_id", "flow_id", "tenant_id"],
        ["file_id", "flow_id", "tenant_id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE {_STEP_INPUT_FILES_TABLE} "
        f"VALIDATE CONSTRAINT {_STEP_INPUT_RUNTIME_UPLOAD_FK}"
    )


def downgrade() -> None:
    op.drop_constraint(
        _STEP_INPUT_RUNTIME_UPLOAD_FK,
        _STEP_INPUT_FILES_TABLE,
        type_="foreignkey",
    )
    op.drop_table(_RUNTIME_UPLOADS_TABLE)
