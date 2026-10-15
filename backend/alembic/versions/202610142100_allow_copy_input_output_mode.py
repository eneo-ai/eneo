"""allow copy_input output mode

The CHECK on flow_steps.output_mode is installed NOT VALID inside the DDL
transaction (a short exclusive lock, no row scan) and validated afterwards in
its own autocommit statement, which lets reads and writes of flow_steps go on
during the scan. The first part is committed when the second begins. When the
validation does not get its lock in time, the revision fails with the new
check installed for new rows and not validated; running the revision again
drops and installs it again and validates it.

The downgrade refuses, with a count, while a flow step holds 'copy_input':
such steps are replaced or deleted first. A step stored between that count
and the installation of the narrower check makes the validation fail instead;
the check then holds for new rows, and the downgrade is run again once the
step is changed. A published version keeps a copy step in its definition
JSON, which no CHECK covers; it needs a runtime that understands copy_input.

Revision ID: 202610142100
Revises: 202610121300
Create Date: 2026-10-14 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "202610142100"
down_revision: str | tuple[str, ...] | None = "202610121300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flow_steps"
_CONSTRAINT = "ck_flow_steps_output_mode"
_EARLIER_MODES = (
    "'pass_through','compose_text','http_post','transcribe_only',"
    "'template_fill','render_verbatim','speaker_mapping'"
)
_MODES = f"{_EARLIER_MODES},'copy_input'"


def _install_constraint(modes: str) -> None:
    """Drop and re-add the check without scanning the rows; the validation
    runs separately, outside the DDL transaction."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (output_mode IN ({modes})) NOT VALID"
    )


def _validate_constraint() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}")
        finally:
            op.execute("RESET lock_timeout")


def count_copy_steps(connection: Connection) -> int:
    """The flow steps that only the wider check admits."""
    return int(
        connection.execute(
            sa.text(f"SELECT count(*) FROM {_TABLE} WHERE output_mode = 'copy_input'")
        ).scalar_one()
    )


def upgrade() -> None:
    _install_constraint(_MODES)
    _validate_constraint()


def downgrade() -> None:
    # The count waits for the table's lock like the DDL does, so the wait is
    # bounded before it. Offline (`alembic downgrade --sql`) there is no
    # database to count in, so only the static DDL is emitted.
    op.execute("SET LOCAL lock_timeout = '5s'")
    if not op.get_context().as_sql:
        copy_steps = count_copy_steps(op.get_bind())
        if copy_steps:
            raise RuntimeError(
                f"Refusing to downgrade 202610142100: {copy_steps} flow step(s) "
                "have output_mode 'copy_input', which the previous check does "
                "not allow. Replace or delete those steps first."
            )
    _install_constraint(_EARLIER_MODES)
    _validate_constraint()
