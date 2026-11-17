"""Who a conversation is with: its source.

A session has exactly one principal (``ck_sessions_single_principal``): a
signed-in user (``user_id``), a service API key (``api_key_id``) or a widget
visitor (``widget_id`` with a pseudonymous ``visitor_id``). That principal is
the conversation's source.

Insights and analytics count every source and tag each conversation with it.
Only a user source is a person: user counts and per-user views read user
sessions only, and an API-key or widget conversation is never attributed to
anyone.

API-key and widget sessions have no ``users`` row, so a read that counts
conversations never scopes its tenant through ``users``. A question read
filters ``Questions.tenant_id``. A session read goes through the
conversation's assistant or group chat and its space: :func:`target_in_tenant`
for one target, :func:`session_in_tenant` for every session of a tenant.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces

SessionSource = Literal["user", "api_key", "widget"]
SESSION_SOURCES: tuple[SessionSource, ...] = ("user", "api_key", "widget")


def session_source() -> sa.ColumnElement[str]:
    """The source of the row's session, as ``'user'``, ``'api_key'`` or
    ``'widget'``. Python twin: :func:`source_of`."""
    return sa.case(
        (Sessions.user_id.is_not(None), sa.literal("user")),
        (Sessions.api_key_id.is_not(None), sa.literal("api_key")),
        else_=sa.literal("widget"),
    )


def source_of(
    *, user_id: UUID | None, api_key_id: UUID | None, widget_id: UUID | None
) -> SessionSource:
    """:func:`session_source` for a session already read; the two must agree."""
    if user_id is not None:
        return "user"
    if api_key_id is not None:
        return "api_key"
    return "widget"


def has_source(source: SessionSource | None) -> sa.ColumnElement[bool]:
    """Sessions of this source; every session when ``source`` is None."""
    if source is None:
        return sa.true()
    principal = {
        "user": Sessions.user_id,
        "api_key": Sessions.api_key_id,
        "widget": Sessions.widget_id,
    }[source]
    return principal.is_not(None)


def target_in_tenant(
    *,
    assistant_id: UUID | None,
    group_chat_id: UUID | None,
    tenant_id: UUID,
) -> sa.ColumnElement[bool]:
    """True when the one assistant or group chat a read is about lives in a
    space of this tenant.

    Uncorrelated, so the database evaluates it once per statement; the read
    itself filters ``Sessions.assistant_id`` or ``Sessions.group_chat_id``.
    """
    if (assistant_id is None) == (group_chat_id is None):
        raise ValueError("Exactly one of assistant_id or group_chat_id is required")
    if assistant_id is not None:
        target = (
            sa.select(Assistants.id)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Assistants.id == assistant_id)
        )
    else:
        target = (
            sa.select(GroupChatsTable.id)
            .join(Spaces, Spaces.id == GroupChatsTable.space_id)
            .where(GroupChatsTable.id == group_chat_id)
        )
    return sa.exists(target.where(Spaces.tenant_id == tenant_id))


def session_in_tenant(tenant_id: UUID) -> sa.ColumnElement[bool]:
    """True for a session whose assistant or group chat lives in a space of
    this tenant, whoever its principal is.

    Each side is an uncorrelated set of the tenant's assistant or group chat
    ids, which the database builds once per statement.
    """
    tenant_assistants = (
        sa.select(Assistants.id)
        .join(Spaces, Spaces.id == Assistants.space_id)
        .where(Spaces.tenant_id == tenant_id)
    )
    tenant_group_chats = (
        sa.select(GroupChatsTable.id)
        .join(Spaces, Spaces.id == GroupChatsTable.space_id)
        .where(Spaces.tenant_id == tenant_id)
    )
    return sa.or_(
        Sessions.assistant_id.in_(tenant_assistants),
        Sessions.group_chat_id.in_(tenant_group_chats),
    )
