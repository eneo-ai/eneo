"""Record the input payload each accepted rerun replaced.

A rerun overwrites the run's input payload in place, so the chain from the
original submission to the values a step actually consumed could not be
rebuilt. Each accepted rerun now stores the payload it replaced, along with
canonical hashes of both sides and the field paths that changed.

Columns are nullable: operations accepted before this migration have no prior
payload to backfill, and that absence is honest rather than reconstructed.

Revision ID: 202607250930_rerun_input_revision
Revises: 202607232300_flow_run_job_index
Create Date: 2026-07-25 09:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202607250930_rerun_input_revision"
down_revision = "202607232300_flow_run_job_index"
branch_labels = None
depends_on = None

_TABLE_NAME = "flow_run_rerun_operations"
_COLUMN_NAMES = (
    "prior_input_hash",
    "resulting_input_hash",
    "changed_input_paths",
    "prior_input_payload_json",
)


def upgrade() -> None:
    op.add_column(_TABLE_NAME, sa.Column("prior_input_hash", sa.String(64)))
    op.add_column(_TABLE_NAME, sa.Column("resulting_input_hash", sa.String(64)))
    op.add_column(_TABLE_NAME, sa.Column("changed_input_paths", JSONB))
    op.add_column(_TABLE_NAME, sa.Column("prior_input_payload_json", JSONB))


def downgrade() -> None:
    for column_name in reversed(_COLUMN_NAMES):
        op.drop_column(_TABLE_NAME, column_name)
