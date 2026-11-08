# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from eneo.roles.role import RoleInDB
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB, UserState
from eneo.widgets.domain.visitor import WidgetVisitorContext
from eneo.widgets.domain.widget import Widget


def build_visitor_user(
    widget: Widget, visitor_id: UUID, tenant: TenantInDB, *, preview: bool = False
) -> UserInDB:
    """Synthetic ``UserInDB`` for an anonymous widget visitor.

    Same pattern as service keys: no ``users`` row, no tenant permissions,
    and ``active_widget`` is the only thing the space actor and the session
    service key on. The id is the visitor id so logs correlate with the
    session's ``visitor_id`` without ever being persisted as ``user_id``.
    """
    assert widget.id is not None
    role = RoleInDB(
        id=widget.id,
        tenant_id=widget.tenant_id,
        name=f"Widget Visitor Role ({widget.name})",
        permissions=[],
    )
    return UserInDB(
        id=visitor_id,
        email=f"visitor-{visitor_id.hex[:12]}@widget-visitor.eneo",
        username=f"Widget visitor ({widget.public_id})",
        state=UserState.ACTIVE,
        tenant_id=widget.tenant_id,
        tenant=tenant,
        active_widget=WidgetVisitorContext(
            widget_id=widget.id,
            visitor_id=visitor_id,
            tenant_id=widget.tenant_id,
            space_id=widget.space_id,
            target_id=widget.target_id,
            token_generation=widget.token_generation,
            preview=preview,
            never_persist=widget.privacy.never_persists,
        ),
        roles=[role],
        used_tokens=0,
        email_verified=True,
        is_active=True,
    )
