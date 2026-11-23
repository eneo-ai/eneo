"""Record where a Flow file came from: its space, its flow and its run.

Three nullable columns on ``files``. A file created for a flow (an upload to a
published step, a Word template) carries its space and flow; a file a run
creates also carries the run. The values are written when the file is created
and never change. They are facts for whoever looks for a file's source, and
they grant no access: reads, changes and deletions never check them. NULL
means that no origin was recorded (a file uploaded outside Flows, or created
before this revision), not that the file is an ordinary one. Existing rows are
not backfilled.

The columns have no foreign keys: CASCADE would delete the file with its flow,
RESTRICT would stop run-history purging and space deletion, and SET NULL would
lose the origin. They have no index.

Cost: adding nullable columns without a default changes only the catalogue.
The check is added NOT VALID and then validated, which reads ``files`` once.
This revision has no autocommit block, so its steps share one transaction and
this does not shorten the lock on ``files``; upgrade with the application
stopped.

The downgrade drops the columns and the check, and with them every recorded
origin. Upgrading again leaves those files with NULL. A downgrade below
``202608201100`` commits this drop when an autocommit block in a revision
between the two begins, so if that downgrade is then refused (service-owned
files exist), the origins are already gone.

Revision ID: 202611181900
Revises: 202611111000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611181900"
down_revision: str | None = "202611111000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_RECORDED = (
    "NULL means not recorded, not an ordinary file. A fact, never an access grant."
)
_COLUMNS = {
    "origin_space_id": f"Space of the flow the file was created for. {_NOT_RECORDED}",
    "origin_flow_id": f"Flow the file was created for. {_NOT_RECORDED}",
    "origin_flow_run_id": (
        "Flow run that created the file; NULL for an upload or a template. "
        f"{_NOT_RECORDED}"
    ),
}
_CHECK = "ck_files_origin"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for name, comment in _COLUMNS.items():
        op.add_column(
            "files", sa.Column(name, sa.Uuid(), nullable=True, comment=comment)
        )
    op.create_check_constraint(
        _CHECK,
        "files",
        "(origin_space_id IS NULL AND origin_flow_id IS NULL "
        "AND origin_flow_run_id IS NULL) "
        "OR (origin_space_id IS NOT NULL AND origin_flow_id IS NOT NULL)",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE files VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CHECK, "files", type_="check")
    for name in reversed(_COLUMNS):
        op.drop_column("files", name)
