"""add document templates

A tenant library of Word templates that generated documents are rendered
into, with one default, and each assistant's choice (inherit the default, a
selected template, or Eneo's built-in) in a table of its own, so the choice
outlives toggling the file-creation capability.

Revision ID: 202610091000
Revises: 202610011100
Create Date: 2026-10-09 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610091000"
down_revision: str | None = "202610011100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content", postgresql.BYTEA(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("syntax", sa.String(), server_default="unknown", nullable=False),
        sa.Column(
            "placeholders",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.String(), server_default="unchecked", nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "syntax IN ('controls', 'braces', 'mixed', 'none', 'unknown')",
            name="ck_document_templates_syntax",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'invalid', 'unchecked')",
            name="ck_document_templates_status",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_templates_size_bytes"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_templates_tenant_id", "document_templates", ["tenant_id"]
    )
    op.create_index(
        "ix_document_templates_tenant_default",
        "document_templates",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_document_templates_tenant_name",
        "document_templates",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "assistant_document_templates",
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("document_template_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "mode IN ('default', 'selected', 'builtin')",
            name="ck_assistant_document_templates_mode",
        ),
        sa.CheckConstraint(
            "(mode = 'selected') = (document_template_id IS NOT NULL)",
            name="ck_assistant_document_templates_pair",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_template_id"], ["document_templates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("assistant_id"),
    )
    op.create_index(
        "ix_assistant_document_templates_document_template_id",
        "assistant_document_templates",
        ["document_template_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_document_templates_document_template_id",
        table_name="assistant_document_templates",
    )
    op.drop_table("assistant_document_templates")
    op.drop_index("ix_document_templates_tenant_name", table_name="document_templates")
    op.drop_index(
        "ix_document_templates_tenant_default", table_name="document_templates"
    )
    op.drop_index("ix_document_templates_tenant_id", table_name="document_templates")
    # DATA LOSS: drops every uploaded document template.
    op.drop_table("document_templates")
