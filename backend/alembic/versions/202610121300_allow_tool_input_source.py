"""allow tool input source

The CHECK on flow_steps.input_source is installed NOT VALID inside the DDL
transaction (a short exclusive lock, no row scan) and validated afterwards in
its own autocommit statement, which lets reads and writes of flow_steps go on
during the scan. The first part is committed when the second begins. When the
validation does not get its lock in time, the revision fails with the new
check installed for new rows and not validated; running the revision again
drops and installs it again and validates it.

The downgrade refuses, with a count, while a flow step holds 'tool': such
steps are changed or deleted first. A step stored between that count and the
installation of the narrower check makes the validation fail instead; the
check then holds for new rows, and the downgrade is run again once the step
is changed. A published version keeps a tool step in its definition JSON,
which no CHECK covers.

Revision ID: 202610121300
Revises: 202610141005
Create Date: 2026-10-12 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "202610121300"
down_revision: str | tuple[str, ...] | None = "202610141005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flow_steps"
_CONSTRAINT = "ck_flow_steps_input_source"
_EARLIER_SOURCES = "'flow_input','previous_step','all_previous_steps','http_get'"
_SOURCES = f"{_EARLIER_SOURCES},'tool'"


def _install_constraint(sources: str) -> None:
    """Drop and re-add the check without scanning the rows; the validation
    runs separately, outside the DDL transaction."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (input_source IN ({sources})) NOT VALID"
    )


def _validate_constraint() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}")
        finally:
            op.execute("RESET lock_timeout")


def count_tool_steps(connection: Connection) -> int:
    """The flow steps that only the wider check admits."""
    return int(
        connection.execute(
            sa.text(f"SELECT count(*) FROM {_TABLE} WHERE input_source = 'tool'")
        ).scalar_one()
    )


def upgrade() -> None:
    _install_constraint(_SOURCES)
    _validate_constraint()


def downgrade() -> None:
    # The count waits for the table's lock like the DDL does, so the wait is
    # bounded before it. Offline (`alembic downgrade --sql`) there is no
    # database to count in, so only the static DDL is emitted.
    op.execute("SET LOCAL lock_timeout = '5s'")
    if not op.get_context().as_sql:
        tool_steps = count_tool_steps(op.get_bind())
        if tool_steps:
            raise RuntimeError(
                f"Refusing to downgrade 202610121300: {tool_steps} flow step(s) "
                "have input_source 'tool', which the previous check does not "
                "allow. Change or delete those steps first."
            )
    _install_constraint(_EARLIER_SOURCES)
    _validate_constraint()
