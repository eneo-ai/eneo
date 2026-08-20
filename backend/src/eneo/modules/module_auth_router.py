from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from eneo.authentication.auth_dependencies import require_session_auth
from eneo.main.container.container import Container
from eneo.main.exceptions import UnauthorizedException
from eneo.modules.module_auth import (
    ModuleResourceSessionResponse,
    ModuleTicketRequest,
    ModuleTicketResponse,
    ModuleTokenRequest,
    ModuleTokenResponse,
    ModuleTokenUser,
)
from eneo.server.dependencies.container import get_container
from eneo.server.dependencies.module_auth import (
    get_module_request_container,
    module_principal_from_request,
)
from eneo.server.protocol import responses

router = APIRouter()

_AuthContainer = Annotated[
    Container,
    Depends(get_container(with_user=True, transaction_scope="function")),
]
_ModuleRequestContainer = Annotated[
    Container,
    Depends(get_module_request_container),
]


@router.post(
    "/tickets/",
    response_model=ModuleTicketResponse,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Issue a one-time, short-lived login ticket for a module. "
        "The request identifies the module by its stable public `module_key`, "
        "not its internal database UUID. "
        "Requires a session token; the frontend redirects the browser to "
        "`redirect_target`, which is the ticket's only carrier - the module "
        "exchanges the ticket server-side. A module-supplied `state` value is "
        "echoed on `redirect_target` so the module can bind the callback to "
        "the browser session that initiated the login (login-CSRF protection)."
    ),
    responses=responses.get_responses([400, 401, 403, 404]),
    dependencies=[Depends(require_session_auth)],
)
async def issue_module_ticket(
    payload: ModuleTicketRequest,
    container: _AuthContainer,
) -> ModuleTicketResponse:
    broker = container.module_auth_broker()
    user = container.user()

    return await broker.issue_ticket(
        user=user,
        module_key=payload.module_key,
        redirect_uri=payload.redirect_uri,
        state=payload.state,
    )


@router.post(
    "/token/",
    response_model=ModuleTokenResponse,
    description=(
        "Exchange a one-time login ticket for a short-lived, module-scoped "
        "user token. Requires the sk_ service key registered for the ticket's "
        "module; the ticket is consumed atomically and cannot be reused."
    ),
    responses=responses.get_responses([401, 403]),
)
async def exchange_module_ticket(
    payload: ModuleTokenRequest,
    request: Request,
    container: _AuthContainer,
) -> ModuleTokenResponse:
    api_key = getattr(request.state, "api_key", None)
    if api_key is None:
        raise UnauthorizedException(
            "Module ticket exchange requires API key authentication."
        )

    broker = container.module_auth_broker()
    return await broker.exchange_ticket(api_key=api_key, ticket=payload.ticket)


@router.post(
    "/{module_key}/token/refresh/",
    response_model=ModuleTokenResponse,
    description=(
        "Renew a still-valid module user token inside the session ceiling. "
        "Requires the same dual credentials as any module resource call - the "
        "bound sk_ service key and the current, unexpired Bearer token - and "
        "re-validates live user, tenant and module-assignment state before "
        "minting. The new token carries the original handoff time, so refresh "
        "slides the token window but can never extend the session past "
        "`session_expires_at`; after the ceiling, or once the token has "
        "expired, the module must run a new login handoff."
    ),
    responses=responses.get_responses([401, 403, 404]),
    openapi_extra={
        "security": [{"OAuth2PasswordBearer": [], "APIKeyHeader": []}],
    },
)
async def refresh_module_token(
    request: Request,
    container: _ModuleRequestContainer,
) -> ModuleTokenResponse:
    principal = module_principal_from_request(request)
    broker = container.module_auth_broker()
    return await broker.refresh_token(principal=principal)


@router.get(
    "/{module_key}/session/",
    response_model=ModuleResourceSessionResponse,
    description=(
        "Validate a module service key and module-user Bearer token together, "
        "including their current tenant, module assignment and user state. "
        "Module resource routes must enforce the same dependency directly; "
        "calling this diagnostic endpoint first does not authorize a later call."
    ),
    responses=responses.get_responses([401, 403, 404]),
    openapi_extra={
        "security": [{"OAuth2PasswordBearer": [], "APIKeyHeader": []}],
    },
)
async def validate_module_resource_session(
    request: Request,
    container: _ModuleRequestContainer,
) -> ModuleResourceSessionResponse:
    principal = module_principal_from_request(request)
    user = container.user()
    return ModuleResourceSessionResponse(
        module_key=principal.module.name,
        tenant_id=user.tenant_id,
        user=ModuleTokenUser(
            id=user.id,
            email=user.email,
            username=user.username,
        ),
    )
