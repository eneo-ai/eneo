"""The browser session: password sign-in, sign-out and the session probe.

Behind ``BROWSER_SESSION_ENABLED`` (404 while it is off). Sign-in and sign-out
run the Sec-Fetch-Site gate before anything else: a cross-site form must not
sign the browser in as someone else (login CSRF) or out. The session token
only ever travels in the HttpOnly cookie, never in a body.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from fastapi.security import OAuth2PasswordRequestForm

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.browser_session import (
    SAFE_METHODS,
    admitted_session_generation,
    clear_session_cookies,
    gate_allows,
    refuse_superseded_session,
    session_cookie,
    set_session_cookie,
)
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB
from eneo.users.user_router import login_with_password


def _admit(request: Request) -> None:
    """404 while the setting is off; the Sec-Fetch-Site gate for writes."""
    if not get_settings().browser_session_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if request.method not in SAFE_METHODS and not gate_allows(request):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "browser_origin_refused",
                "message": "This request did not come from a page of this site.",
            },
        )


class _BrowserSessionRoute(APIRoute):
    """Runs ``_admit`` before FastAPI reads the body or solves dependencies.

    FastAPI parses a form body before any dependency runs, so a gate there
    would come after multipart parsing (and the temporary files of any file
    part), and a malformed body would answer 400 instead of 404 or 403.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def admitted(request: Request) -> Response:
            _admit(request)
            return await handle(request)

        return admitted


router = APIRouter(
    prefix="/auth", tags=["authentication"], route_class=_BrowserSessionRoute
)


@router.post(
    "/session/password/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Sign in the browser",
    description=(
        "Sign the browser in with email and password. Sets the HttpOnly session "
        "cookie and returns no body; failures are those of `/users/login/token/`. "
        "Only for requests from the site's own pages."
    ),
    responses=responses.get_responses([401, 403, 404, 429, 500]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Login entry point; login_with_password validates the supplied credentials, and the Sec-Fetch-Site gate refuses other sites' forms.",
)
async def create_browser_session(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    container: Annotated[
        Container, Depends(get_container(transaction_scope="function"))
    ],
) -> Response:
    token = await login_with_password(
        request=request,
        email=form_data.username,
        password=form_data.password,
        container=container,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # A new token every time, never one the request brought (session fixation).
    set_session_cookie(response, token.access_token, settings=get_settings())
    return response


@router.post(
    "/session/logout/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Sign out the browser",
    description=(
        "Clear the browser's session cookies. Sign-out is local: the token is "
        "not revoked. With `Eneo-Session-Generation`, a session other than "
        "the one named is left in place (401). Only for requests from the "
        "site's own pages."
    ),
    responses=responses.get_responses([401, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Sign-out must also clear a session that no longer authenticates; the Sec-Fetch-Site gate refuses other sites' requests.",
)
async def end_browser_session(
    request: Request,
) -> Response:
    settings = get_settings()
    token = session_cookie(request, settings)
    if token is not None:
        refuse_superseded_session(request, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings=settings)
    return response


@router.get(
    "/session/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    name="Check the browser session",
    description=(
        "Authenticate the browser's session cookie and name its generation in "
        "`Eneo-Session-Generation`. A Bearer token is not a browser session (401)."
    ),
    responses=responses.get_responses([401, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason="Any signed-in browser may check its own session; it reveals only a fingerprint of the caller's cookie.",
    reachable_before_password_change=True,
)
async def get_browser_session(
    request: Request,
    _user: Annotated[UserInDB, Depends(get_current_active_user)],
) -> Response:
    if admitted_session_generation(request.scope) is None:
        raise AuthenticationException("No browser session")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
