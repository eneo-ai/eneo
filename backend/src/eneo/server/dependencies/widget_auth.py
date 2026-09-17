# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated, Optional

from fastapi import Depends, Request

from eneo.authentication.api_key_request_context import resolve_client_ip
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    WidgetNotActiveError,
)
from eneo.widgets.domain.visitor import WidgetPrincipal
from eneo.widgets.domain.widget import Widget, WidgetStatus, is_public_id

# The anonymous widget surface never resolves an Eneo user; the container
# carries only the request session.
PublicContainer = Annotated[Container, Depends(get_container())]


async def get_active_widget(public_id: str, container: PublicContainer) -> Widget:
    """Resolve an active widget by its public id; anything else is 404.

    A malformed id, an unknown id and a paused/archived widget all answer the
    same way so the public surface leaks nothing about what exists.
    """
    if not is_public_id(public_id):
        raise WidgetNotActiveError()
    widget = await container.widget_repo().get_by_public_id(public_id)
    if widget is None or widget.status != WidgetStatus.ACTIVE:
        raise WidgetNotActiveError()
    return widget


ActiveWidget = Annotated[Widget, Depends(get_active_widget)]


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


async def get_widget_principal(
    request: Request, widget: ActiveWidget, container: PublicContainer
) -> WidgetPrincipal:
    token = bearer_token(request)
    if token is None:
        raise VisitorTokenInvalidError("Visitor token required.")
    claims = container.widget_visitor_token_service().verify(token, widget)
    return WidgetPrincipal(widget=widget, visitor_id=claims.visitor_id, claims=claims)


VisitorPrincipal = Annotated[WidgetPrincipal, Depends(get_widget_principal)]


def client_ip(request: Request) -> Optional[str]:
    settings = get_settings()
    return resolve_client_ip(
        request,
        trusted_proxy_count=settings.trusted_proxy_count,
        trusted_proxy_headers=settings.trusted_proxy_headers,
    )
