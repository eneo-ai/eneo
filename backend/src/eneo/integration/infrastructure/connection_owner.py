"""Whose personal connection may still sync: an owner who can still sign in.

A personal (user OAuth) connection syncs with its owner's token, which Graph
keeps honouring after Eneo deactivates or deletes the owner. Every path that
queues a sync of such a connection applies this one rule, so the connection
stops syncing everywhere at once. An organization (tenant app) connection has
no owner and is not subject to it.
"""

import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.users.user import UserState

_STATES_THAT_CAN_SIGN_IN = (UserState.ACTIVE.value, UserState.INVITED.value)


def owner_can_sign_in() -> sa.ColumnElement[bool]:
    """True for an owner who can still sign in; needs ``Users`` joined on the
    connection's ``user_id`` (an outer join leaves no owner, which is false)."""
    return sa.and_(
        Users.deleted_at.is_(None),
        Users.state.in_(_STATES_THAT_CAN_SIGN_IN),
    )
