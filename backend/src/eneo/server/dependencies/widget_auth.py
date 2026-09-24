# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated, Optional

from fastapi import Depends, Request

from eneo.authentication.api_key_request_context import resolve_client_ip
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.server.dependencies.container import get_container
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
)
from eneo.widgets.domain.visitor import WidgetPrincipal
from eneo.widgets.domain.widget import Widget

# The anonymous widget surface never resolves an Eneo user; the container
# carries only the request session.
PublicContainer = Annotated[Container, Depends(get_container())]


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


async def get_active_widget(
    request: Request, public_id: str, container: PublicContainer
) -> Widget:
    return await container.widget_authentication_service().get_active_widget(
        public_id, preview_token=bearer_token(request)
    )


ActiveWidget = Annotated[Widget, Depends(get_active_widget)]


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


async def get_visitor_container(
    request: Request, principal: VisitorPrincipal, container: PublicContainer
) -> Container:
    """A request container whose user is the synthetic widget visitor.

    Everything downstream (space actor, session service, assistant service)
    then treats the visitor exactly like any other principal; the widget is
    its only access path and sessions are owned by widget + visitor.
    """
    user = await container.widget_authentication_service().resolve_user(
        principal.widget, principal.visitor_id, preview=principal.claims.preview
    )
    override_user(container=container, user=user)
    request.state.widget_principal = principal
    return container


VisitorContainer = Annotated[Container, Depends(get_visitor_container)]
