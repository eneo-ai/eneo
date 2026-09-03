"""add typed job failure codes

Revision ID: 202607301200
Revises: 202607301100
Create Date: 2026-07-30 12:00:00.000000

Legacy failed jobs retain their existing result_location prose and receive no
inferred code. Those messages are unstructured and cannot be backfilled safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607301200"
down_revision: str | None = "202607301100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


def _lock_jobs_for_schema_change() -> None:
    try:
        op.get_bind().exec_driver_sql("LOCK TABLE jobs IN ACCESS EXCLUSIVE MODE NOWAIT")
    except sa.exc.DBAPIError as error:
        sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
            error.orig,
            "pgcode",
            None,
        )
        if sqlstate != _LOCK_NOT_AVAILABLE_SQLSTATE:
            raise
        raise RuntimeError(
            "Job failure-code migration could not lock jobs; stop all API "
            "replicas and workers, then retry db-init"
        ) from error


def upgrade() -> None:
    _lock_jobs_for_schema_change()
    op.add_column(
        "jobs",
        sa.Column("failure_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "failure_code")
