"""Let a file be owned by a person or by a service principal.

A file was owned by ``files.user_id``, so only a person could own one and a
service key could not upload. The owner is now one of two columns, chosen by
``owner_type``: ``owner_user_id`` for a person, ``owner_service_id`` for the
service principal behind a service key.

Every existing file stays a person's file. No row is rewritten: ``user_id``
is renamed to ``owner_user_id``, and ``owner_type`` gets a constant default.

The users key changes from CASCADE to RESTRICT, because Postgres cannot
change the ON DELETE rule of an existing key. Validating the two owner keys
and the two owner checks, and building the service-owner index, each read the
whole table. This revision runs in one transaction, so ``files`` stays locked
until it commits. Upgrade with the application stopped.

Revision ID: 202611241100
Revises: 202611241000
Create Date: 2026-11-24 11:00:00.000000
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611241100"
down_revision: str = "202611241000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_validated_check(table: str, name: str, condition: str) -> None:
    op.create_check_constraint(
        name,
        table,
        condition,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    logger = logging.getLogger("alembic.runtime.migration")
    op.add_column(
        "files",
        sa.Column(
            "owner_type",
            sa.String(),
            nullable=False,
            server_default="user",
        ),
    )
    op.alter_column(
        "files",
        "user_id",
        new_column_name="owner_user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "files",
        sa.Column("owner_service_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint("files_users_fkey", "files", type_="foreignkey")
    logger.info("files: renamed user_id to owner_user_id without rewriting any row")
    op.create_foreign_key(
        "fk_files_owner_user_id",
        "files",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        "fk_files_owner_service_id",
        "files",
        "service_principals",
        ["owner_service_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    estimated_rows = (
        0
        if op.get_context().as_sql
        else op.get_bind().scalar(
            sa.text(
                "SELECT reltuples::bigint FROM pg_class WHERE oid = 'files'::regclass"
            )
        )
    )
    logger.info(
        "files: validating the owner keys and checks and building the service-owner "
        "index; each step reads the whole table (%s)",
        f"planner estimate: {estimated_rows} rows"
        if estimated_rows > 0
        else "no row estimate yet",
    )
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT fk_files_owner_user_id")
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT fk_files_owner_service_id")
    _add_validated_check(
        "files",
        "ck_files_owner_type",
        "owner_type IN ('user','service_key')",
    )
    _add_validated_check(
        "files",
        "ck_files_owner_identity",
        "(owner_type = 'user' AND owner_user_id IS NOT NULL "
        "AND owner_service_id IS NULL) OR "
        "(owner_type = 'service_key' AND owner_user_id IS NULL "
        "AND owner_service_id IS NOT NULL)",
    )
    op.create_index(
        "ix_files_service_owner_created_at",
        "files",
        ["tenant_id", "owner_service_id", "created_at"],
        postgresql_where=sa.text("owner_type = 'service_key'"),
    )


def downgrade() -> None:
    # A file a service owns has no person to go back to. Refuse instead of
    # guessing an owner or deleting the file.
    service_owned_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM files WHERE owner_type = 'service_key'"))
        .scalar_one()
    )
    if service_owned_count:
        raise RuntimeError(
            "Cannot remove the file owner columns while "
            f"{service_owned_count} files are owned by a service principal. "
            "Delete those files first."
        )
    op.drop_index("ix_files_service_owner_created_at", table_name="files")
    op.drop_constraint("ck_files_owner_identity", "files", type_="check")
    op.drop_constraint("ck_files_owner_type", "files", type_="check")
    op.drop_constraint("fk_files_owner_service_id", "files", type_="foreignkey")
    op.drop_constraint("fk_files_owner_user_id", "files", type_="foreignkey")
    op.drop_column("files", "owner_service_id")
    op.drop_column("files", "owner_type")
    op.alter_column(
        "files",
        "owner_user_id",
        new_column_name="user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "files_users_fkey",
        "files",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
