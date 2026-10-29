"""Browser sessions: password and federated sign-in, sign-out and the probe.

Behind ``BROWSER_SESSION_ENABLED`` (404 while it is off). Password sign-in and
sign-out run the Sec-Fetch-Site gate before body parsing. Federation initiation
also uses that gate; cross-site IdP callbacks instead require signed state bound
to this browser's transaction. The session token only travels in the HttpOnly
cookie, never in a body.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.routing import APIRoute
from fastapi.security import OAuth2PasswordRequestForm
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import Message, Receive, Scope, Send

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.browser_session import (
    SAFE_METHODS,
    admitted_session_generation,
    clear_session_cookies,
    clear_transaction_cookie,
    gate_allows,
    refuse_superseded_session,
    safe_next_path,
    session_cookie,
    set_session_cookie,
    set_transaction_cookie,
    transaction_cookie,
)
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.authentication.federation_router import (
    CallbackRequest,
    auth_callback,
    initiate_auth,
)
from eneo.main.config import LOOPBACK_HOSTS, get_settings, validate_content_base_url
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger
from eneo.main.request_context import ensure_correlation_id
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB
from eneo.users.user_router import login_with_password

logger = get_logger(__name__)


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


def _federation_failure(
    detail_code: str, correlation: str | None = None
) -> RedirectResponse:
    query = {"message": "oidc_callback_failed", "detailCode": detail_code}
    if correlation:
        query["correlation"] = correlation[:1000]
    return RedirectResponse(
        "/login?" + urlencode(query),
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


def _http_federation_failure(
    status_code: int, correlation: str | None = None
) -> RedirectResponse:
    code = {403: "access_denied", 401: "unauthorized"}.get(
        status_code, f"http_{status_code}"
    )
    return _federation_failure(code, correlation)


@router.get(
    "/browser/initiate",
    include_in_schema=False,
    response_model=None,
    description="Start a browser SSO transaction using a registered callback on this host.",
    responses={
        303: {"description": "Continue to the IdP or sign-in failure."},
        **responses.get_responses([400, 404]),
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Starts a signed OIDC transaction on the site's own navigation; the federation owner validates the tenant and registered callback.",
    effect_on_get="Creates a short-lived transaction cookie and single-use state after the Sec-Fetch-Site gate. Does not change the signed-in identity.",
)
async def initiate_browser_federation(
    request: Request,
    container: Annotated[Container, Depends(get_container())],
    tenant: Annotated[str | None, Query(pattern=r"^[a-z0-9-]+$")] = None,
    next: str | None = None,
    prompt: str | None = None,
) -> Response:
    if not gate_allows(request):
        return _federation_failure("invalid_login_attempt")
    # Organisation switching uses the guarded POST logout and tenant selector.
    if prompt is not None:
        raise HTTPException(400, "A prompt is not supported")
    try:
        scheme = "http" if request.url.hostname in LOOPBACK_HOSTS else "https"
        origin = validate_content_base_url(f"{scheme}://{request.url.netloc}")
    except ValueError:
        return _federation_failure("invalid_login_attempt")
    settings = get_settings()
    transaction = secrets.token_urlsafe(32)
    binding = (
        hashlib.sha256(transaction.encode()).hexdigest() + ":" + safe_next_path(next)
    )
    for path in ("/login/callback", "/auth/callback"):
        metadata = Response()
        try:
            result = await initiate_auth(
                response=metadata,
                container=container,
                tenant=tenant,
                state=binding,
                redirect_uri_param=origin + path,
            )
        except HTTPException as exc:
            if exc.status_code == 400 and exc.detail.startswith(
                "The provided redirect_uri is not registered"
            ):
                continue
            return _http_federation_failure(
                exc.status_code, (exc.headers or {}).get("X-Correlation-ID")
            )
        response = RedirectResponse(
            result.authorization_url,
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
        if correlation := metadata.headers.get("X-Correlation-ID"):
            response.headers["X-Correlation-ID"] = correlation
        set_transaction_cookie(response, transaction, settings=settings)
        return response
    logger.warning(
        "browser_oidc_redirect_not_registered",
        extra={"host": request.url.hostname, "tenant": tenant},
    )
    return _federation_failure("redirect_uri_not_registered")


class _BrowserCallbackRoute(APIRoute):
    """Clear the transaction on every callback outcome, including commit failure.

    IdP navigations are cross-site. Admission belongs to the signed state and
    transaction cookie, not the ordinary same-origin request gate.
    """

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        # FastAPI commits function-scoped dependencies outside get_route_handler.
        # Finish the callback at the ASGI boundary, after that commit succeeds.
        settings = get_settings()
        cleanup = Response()
        clear_transaction_cookie(cleanup, settings=settings)
        started = False
        failed_response = False

        async def send_callback(message: Message) -> None:
            nonlocal started, failed_response
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if message["status"] >= 400 and settings.browser_session_enabled:
                    # Domain/HTTP exceptions may already have been handled by
                    # the application's exception handlers, including at commit.
                    failure = _http_federation_failure(
                        message["status"], headers.get("X-Correlation-ID")
                    )
                    message = {
                        "type": "http.response.start",
                        "status": failure.status_code,
                        "headers": failure.raw_headers,
                    }
                    headers = MutableHeaders(scope=message)
                    failed_response = True
                headers.append("set-cookie", cleanup.headers["set-cookie"])
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
                started = True
            elif message["type"] == "http.response.body" and failed_response:
                message = {**message, "body": b""}
            await send(message)

        if not settings.browser_session_enabled:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            await response(scope, receive, send_callback)
            return
        try:
            await super().handle(scope, receive, send_callback)
        except Exception as exc:
            if started:
                raise
            correlation = ensure_correlation_id()
            logger.error(
                "browser_oidc_callback_failed",
                extra={
                    "error_type": type(exc).__name__,
                    "correlation_id": correlation,
                },
            )
            await _federation_failure("http_500", correlation)(
                scope, receive, send_callback
            )


callback_router = APIRouter(route_class=_BrowserCallbackRoute)


@callback_router.get(
    "/login/callback",
    include_in_schema=False,
    response_model=None,
    description="Complete the browser-bound SSO transaction and end the document.",
    responses={
        303: {"description": "Continue to a safe page or sign-in failure."},
        **responses.get_responses([404]),
    },
)
@callback_router.get(
    "/auth/callback",
    include_in_schema=False,
    response_model=None,
    description="Complete the browser-bound SSO transaction using the alternate callback path.",
    responses={
        303: {"description": "Continue to a safe page or sign-in failure."},
        **responses.get_responses([404]),
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="An IdP callback is admitted only by signed expiring state bound to this browser's transaction; the federation owner consumes state once and validates the identity.",
    effect_on_get="Commits the federated identity and sets a session cookie only after transaction admission, then ends the document with a redirect.",
)
async def complete_browser_federation(
    request: Request,
    container: Annotated[
        Container, Depends(get_container(transaction_scope="function"))
    ],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    settings = get_settings()
    transaction = transaction_cookie(request, settings)
    if not transaction or not state:
        return _federation_failure("invalid_login_attempt")
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "frontend_state"]},
        )
    except jwt.InvalidTokenError:
        return _federation_failure("invalid_login_attempt")
    binding = payload.get("frontend_state")
    if not isinstance(binding, str):
        return _federation_failure("invalid_login_attempt")
    expected, separator, next_path = binding.partition(":")
    if (
        not separator
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
        or not hmac.compare_digest(
            expected, hashlib.sha256(transaction.encode()).hexdigest()
        )
    ):
        return _federation_failure("invalid_login_attempt")
    if error is not None:
        return _federation_failure("identity_provider_error")
    if not code:
        return _federation_failure("no_code_received")
    token = await auth_callback(CallbackRequest(code=code, state=state), container)
    response = RedirectResponse(safe_next_path(next_path), status_code=303)
    set_session_cookie(response, token["access_token"], settings=settings)
    return response
