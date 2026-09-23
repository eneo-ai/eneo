# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated, Optional

from fastapi import Depends, Request

from eneo.authentication.api_key_request_context import resolve_client_ip
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.exceptions import NotFoundException, TenantSuspendedException
from eneo.server.dependencies.container import get_container
from eneo.widgets.application.visitor_user import build_visitor_user
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    WidgetNotActiveError,
    WidgetPublicError,
)
from eneo.widgets.domain.visitor import WidgetPrincipal
from eneo.widgets.domain.widget import Widget, WidgetStatus, is_public_id

# The anonymous widget surface never resolves an Eneo user; the container
# carries only the request session.
PublicContainer = Annotated[Container, Depends(get_container())]


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def _holds_preview_token(
    request: Request, widget: Widget, container: Container
) -> bool:
    token = bearer_token(request)
    if token is None:
        return False
    try:
        claims = container.widget_visitor_token_service().verify(token, widget)
    except WidgetPublicError:
        return False
    return claims.preview


async def get_active_widget(
    request: Request, public_id: str, container: PublicContainer
) -> Widget:
    """Resolve an active widget by its public id; anything else is 404.

    A malformed id, an unknown id, a paused/archived widget and a suspended
    tenant's widget all answer the same way so the public surface leaks
    nothing about what exists. The one
    exception is an editor's preview token, which admits a draft or paused
    widget so the admin page can show the real embed page before activation.
    """
    if not is_public_id(public_id):
        raise WidgetNotActiveError()
    widget = await container.widget_repo().get_by_public_id(public_id)
    if widget is None:
        raise WidgetNotActiveError()
    if widget.status == WidgetStatus.ACTIVE:
        # An assistant unpublished after activation takes its widget offline
        # the same way a pause does, instead of answering with a permission
        # error the embed page cannot explain.
        if not await container.widget_repo().is_target_published(widget):
            raise WidgetNotActiveError()
        return widget
    if widget.status != WidgetStatus.ARCHIVED and _holds_preview_token(
        request, widget, container
    ):
        return widget
    raise WidgetNotActiveError()


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
    widget = principal.widget
    tenant = await container.tenant_repo().get(widget.tenant_id)
    if tenant is None:
        raise NotFoundException("Tenant not found.")
    user = build_visitor_user(widget, principal.visitor_id, tenant)
    try:
        # The same live tenant policy as every other principal; a suspended
        # tenant's widget answers like a paused one.
        await container.user_service().validate_active_identity(
            user, correlation_id="widget-visitor"
        )
    except TenantSuspendedException as exc:
        raise WidgetNotActiveError() from exc
    override_user(container=container, user=user)
    request.state.widget_principal = principal
    return container


VisitorContainer = Annotated[Container, Depends(get_visitor_container)]
