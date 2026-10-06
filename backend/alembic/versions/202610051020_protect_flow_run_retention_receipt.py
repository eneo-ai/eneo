"""protect a Flow run's retention receipt until the run is gone

Revision ID: 202610051020
Revises: 202610051010
Create Date: 2026-10-05 10:20:00.000000

Receipt pruning must not erase the proof that a remaining run's read fence
refers to. The referencing index is concurrent; the validated RESTRICT foreign
key keeps this invariant even when an operator stops or withdraws a receipt.
Historical storage names stay bound to the same data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610051020"
down_revision: str = "202610051010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_flow_runs_retention_receipt"
_CONSTRAINT = "fk_flow_runs_retention_receipt"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            offline = op.get_context().as_sql
            if not offline:
                valid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT indisvalid FROM pg_index "
                            "WHERE indexrelid = to_regclass(:name)"
                        ),
                        {"name": _INDEX},
                    )
                    .scalar()
                )
                if valid is False:
                    op.drop_index(
                        _INDEX, table_name="flow_runs", postgresql_concurrently=True
                    )
            op.create_index(
                _INDEX,
                "flow_runs",
                ["gallring_receipt_id"],
                postgresql_where=sa.text("gallring_receipt_id IS NOT NULL"),
                postgresql_concurrently=True,
                if_not_exists=True,
            )
            exists = (
                False
                if offline
                else op.get_bind()
                .execute(
                    sa.text(
                        "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                        "WHERE conrelid = 'flow_runs'::regclass AND conname = :name)"
                    ),
                    {"name": _CONSTRAINT},
                )
                .scalar()
            )
            if not exists:
                op.execute(
                    "ALTER TABLE flow_runs ADD CONSTRAINT "
                    + _CONSTRAINT
                    + " FOREIGN KEY (gallring_receipt_id) REFERENCES gallring_receipts(id)"
                    " ON DELETE RESTRICT NOT VALID"
                )
            op.execute("ALTER TABLE flow_runs VALIDATE CONSTRAINT " + _CONSTRAINT)
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute("ALTER TABLE flow_runs DROP CONSTRAINT IF EXISTS " + _CONSTRAINT)
            op.drop_index(
                _INDEX,
                table_name="flow_runs",
                postgresql_concurrently=True,
                if_exists=True,
            )
        finally:
            op.execute("RESET lock_timeout")
