from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from eneo.authentication.auth_dependencies import require_session_auth
from eneo.main.container.container import Container
from eneo.main.exceptions import UnauthorizedException
from eneo.modules.module_auth import (
    ModuleTicketRequest,
    ModuleTicketResponse,
    ModuleTokenRequest,
    ModuleTokenResponse,
)
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()

_Container = Annotated[Container, Depends(get_container(with_user=True))]


@router.post(
    "/auth/tickets/",
    response_model=ModuleTicketResponse,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Issue a one-time, short-lived login ticket for a module. "
        "Requires a session token; the frontend redirects the browser to "
        "`redirect_target`, where the module exchanges the ticket server-side."
    ),
    responses=responses.get_responses([400, 401, 403, 404]),
    dependencies=[Depends(require_session_auth)],
)
async def issue_module_ticket(
    payload: ModuleTicketRequest,
    container: _Container,
) -> ModuleTicketResponse:
    broker = container.module_auth_broker()
    user = container.user()

    return await broker.issue_ticket(
        user=user,
        module_id=payload.module_id,
        redirect_uri=payload.redirect_uri,
    )


@router.post(
    "/auth/token/",
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
    container: _Container,
) -> ModuleTokenResponse:
    api_key = getattr(request.state, "api_key", None)
    if api_key is None:
        raise UnauthorizedException(
            "Module ticket exchange requires API key authentication."
        )

    broker = container.module_auth_broker()
    return await broker.exchange_ticket(api_key=api_key, ticket=payload.ticket)
