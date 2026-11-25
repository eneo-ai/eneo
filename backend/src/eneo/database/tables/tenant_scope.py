"""Which organisation a row of ``assistants`` or ``services`` belongs to.

Neither table has a ``tenant_id``. A row belongs to the organisation of its
space. The creator is only a trace and may be empty, so it decides the
organisation solely for an old row that has no space.
"""

from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users


def in_tenant(table: Any, tenant_id: UUID) -> sa.ColumnElement[bool]:
    """Rows of ``table`` (``Assistants`` or ``Services``) of one organisation."""
    return sa.or_(
        table.space_id.in_(sa.select(Spaces.id).where(Spaces.tenant_id == tenant_id)),
        sa.and_(
            table.space_id.is_(None),
            table.user_id.in_(sa.select(Users.id).where(Users.tenant_id == tenant_id)),
        ),
    )


def tenant_id_of(table: Any) -> sa.ColumnElement[UUID | None]:
    """The organisation of a row of ``table``, as a correlated expression."""
    return cast(
        "sa.ColumnElement[UUID | None]",
        sa.func.coalesce(
            sa.select(Spaces.tenant_id)
            .where(Spaces.id == table.space_id)
            .correlate(table)
            .scalar_subquery(),
            sa.select(Users.tenant_id)
            .where(Users.id == table.user_id)
            .correlate(table)
            .scalar_subquery(),
        ),
    )
