"""Let a job belong to a service principal.

A job had to belong to a person, so a service key could queue none: running
an app, starting a crawl or a sync, or uploading knowledge all failed on the
key's id, which is no user.

``jobs.user_id`` may now be empty. ``service_principal_id`` is the owner of a
job a service key queued, and ``api_key_id`` is that key: a trace, and what
lets the worker sign the caller in again. A job has at most one owner.

No row is rewritten and every existing job keeps its person. The two checks
and the two keys are validated, which reads ``jobs`` while it is locked.

Revision ID: 202611251100
Revises: 202611251000
Create Date: 2026-11-25 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611251100"
down_revision: str = "202611251000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLE_OWNER = "ck_jobs_single_owner"
_KEY_REQUIRES_PRINCIPAL = "ck_jobs_api_key_requires_service_principal"
_INDEX = "ix_jobs_service_principal_created"


def _add_validated_check(name: str, condition: str) -> None:
    op.create_check_constraint(name, "jobs", condition, postgresql_not_valid=True)
    op.execute(f"ALTER TABLE jobs VALIDATE CONSTRAINT {name}")


def _add_validated_key(name: str, referred: str, column: str, ondelete: str) -> None:
    op.create_foreign_key(
        name,
        "jobs",
        referred,
        [column],
        ["id"],
        ondelete=ondelete,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE jobs VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.alter_column(
        "jobs",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "jobs",
        sa.Column("service_principal_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_validated_key(
        "fk_jobs_service_principal",
        "service_principals",
        "service_principal_id",
        "RESTRICT",
    )
    _add_validated_key("fk_jobs_api_key", "api_keys_v2", "api_key_id", "SET NULL")
    _add_validated_check(
        _SINGLE_OWNER, "user_id IS NULL OR service_principal_id IS NULL"
    )
    _add_validated_check(
        _KEY_REQUIRES_PRINCIPAL,
        "api_key_id IS NULL OR service_principal_id IS NOT NULL",
    )
    op.create_index(
        _INDEX,
        "jobs",
        ["service_principal_id", "created_at"],
        postgresql_where=sa.text("service_principal_id IS NOT NULL"),
    )


def downgrade() -> None:
    # A job without a person cannot go back to a column that requires one.
    # Jobs are short-lived records of work, not content: refuse, and let the
    # operator remove them.
    without_person = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM jobs WHERE user_id IS NULL"))
        .scalar_one()
    )
    if without_person:
        raise RuntimeError(
            f"Cannot require a person on jobs again: {without_person} jobs "
            "belong to no person. Remove those jobs first."
        )
    op.drop_index(_INDEX, table_name="jobs")
    op.drop_constraint(_KEY_REQUIRES_PRINCIPAL, "jobs", type_="check")
    op.drop_constraint(_SINGLE_OWNER, "jobs", type_="check")
    op.drop_constraint("fk_jobs_api_key", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_service_principal", "jobs", type_="foreignkey")
    op.drop_column("jobs", "api_key_id")
    op.drop_column("jobs", "service_principal_id")
    op.alter_column(
        "jobs",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
