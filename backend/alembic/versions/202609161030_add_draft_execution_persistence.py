"""Add immutable draft execution persistence.

Every existing Flow version was published at creation: publish_flow was the only
writer. Backfill that history from created_at without changing snapshot payloads.

Revision ID: 202609161030
Revises: 202609151000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609161030"
down_revision: str | None = "202609161000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flow_versions",
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_versions", sa.Column("source_draft_revision", sa.Integer(), nullable=True)
    )
    op.execute("UPDATE flow_versions SET first_published_at = created_at")
    op.add_column(
        "flows",
        sa.Column(
            "snapshot_allocation_high_water_mark",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE flows SET snapshot_allocation_high_water_mark = "
        "COALESCE((SELECT MAX(version) FROM flow_versions WHERE flow_id = flows.id), 0)"
    )

    op.add_column(
        "flow_runs",
        sa.Column("purpose", sa.String(), server_default="production", nullable=False),
    )
    op.create_check_constraint(
        "ck_flow_runs_purpose", "flow_runs", "purpose IN ('production','test')"
    )

    op.create_table(
        "flow_version_file_references",
        sa.Column("flow_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("flow_id", "version", "file_id"),
        sa.ForeignKeyConstraint(
            ["flow_id", "version"],
            ["flow_versions.flow_id", "flow_versions.version"],
            ondelete="CASCADE",
            name="fk_flow_version_file_references_version",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_version_file_references_flow_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_version_file_references_file_tenant",
        ),
    )
    op.create_index(
        "ix_flow_version_file_references_file_id",
        "flow_version_file_references",
        ["file_id"],
    )


def downgrade() -> None:
    op.drop_table("flow_version_file_references")
    op.drop_constraint("ck_flow_runs_purpose", "flow_runs", type_="check")
    op.drop_column("flow_runs", "purpose")
    op.drop_column("flows", "snapshot_allocation_high_water_mark")
    op.drop_column("flow_versions", "source_draft_revision")
    op.drop_column("flow_versions", "first_published_at")
