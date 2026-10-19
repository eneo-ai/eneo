"""Token endpoint requests: code exchange, refresh, client credentials,
dynamic registration, revocation and the two ID-JAG legs.

Every request carries the ``resource`` parameter (RFC 8707) as the MCP spec
requires, so the authorization server audience-restricts what it issues.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional, cast

import httpx

from eneo.main.logging import get_logger

logger = get_logger(__name__)

TOKEN_REQUEST_TIMEOUT_SECONDS = 15.0

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ID_JAG_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id-jag"
ID_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
ID_JAG_JWT_TYP = "oauth-id-jag+jwt"

ClientAuthMethod = Literal["none", "client_secret_basic", "client_secret_post"]


class OAuthTokenError(Exception):
    """The authorization server refused a token request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.error_description = error_description

    @property
    def is_invalid_grant(self) -> bool:
        """The refresh token or code is dead; only a new authorization helps."""
        return self.error in ("invalid_grant", "invalid_token")


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]
    scope: Optional[str]

    @property
    def scopes(self) -> Optional[list[str]]:
        return self.scope.split() if self.scope else None


@dataclass(frozen=True)
class ClientCredential:
    client_id: str
    client_secret: Optional[str]
    auth_method: ClientAuthMethod


def choose_client_auth_method(
    client_secret: Optional[str], methods_supported: tuple[str, ...]
) -> ClientAuthMethod:
    if not client_secret:
        return "none"
    if "client_secret_basic" in methods_supported:
        return "client_secret_basic"
    if "client_secret_post" in methods_supported:
        return "client_secret_post"
    # RFC 8414 default when the server lists nothing.
    return "client_secret_basic"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(TOKEN_REQUEST_TIMEOUT_SECONDS), follow_redirects=False
    )


def _apply_client_auth(
    form: dict[str, str], headers: dict[str, str], credential: ClientCredential
) -> None:
    form["client_id"] = credential.client_id
    if credential.auth_method == "client_secret_basic" and credential.client_secret:
        raw = f"{credential.client_id}:{credential.client_secret}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        form.pop("client_id", None)
    elif credential.auth_method == "client_secret_post" and credential.client_secret:
        form["client_secret"] = credential.client_secret


async def _post_form(
    endpoint: str, form: dict[str, str], headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    try:
        async with _client() as http:
            response = await http.post(
                endpoint,
                data=form,
                headers={"Accept": "application/json", **(headers or {})},
            )
    except httpx.HTTPError as exc:
        raise OAuthTokenError(
            f"Token endpoint {endpoint} unreachable: {exc}", status_code=0
        ) from exc
    try:
        payload: object = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return response.status_code, cast(dict[str, Any], payload)


def _raise_for_error(status_code: int, payload: dict[str, Any], what: str) -> None:
    if status_code < 400:
        return
    error = payload.get("error")
    description = payload.get("error_description")
    error_str = error if isinstance(error, str) else None
    description_str = description if isinstance(description, str) else None
    detail = description_str or error_str or f"HTTP {status_code}"
    raise OAuthTokenError(
        f"{what} failed: {detail}",
        status_code=status_code,
        error=error_str,
        error_description=description_str,
    )


def _token_response(payload: dict[str, Any], now: datetime) -> TokenResponse:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthTokenError("Token response carried no access_token", status_code=200)
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    expires_at: Optional[datetime] = None
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
        expires_at = now + timedelta(seconds=float(expires_in))
    elif isinstance(expires_in, str) and expires_in.isdigit():
        expires_at = now + timedelta(seconds=int(expires_in))
    if expires_at is None:
        exp = peek_jwt_claim(access_token, "exp")
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(float(exp), tz=timezone.utc)
    scope = payload.get("scope")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
        if isinstance(refresh_token, str) and refresh_token
        else None,
        expires_at=expires_at,
        scope=scope if isinstance(scope, str) and scope else None,
    )


async def exchange_authorization_code(
    *,
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    resource: str,
    credential: ClientCredential,
) -> TokenResponse:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "resource": resource,
    }
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    status, payload = await _post_form(token_endpoint, form, headers)
    _raise_for_error(status, payload, "Authorization code exchange")
    return _token_response(payload, datetime.now(timezone.utc))


async def refresh_access_token(
    *,
    token_endpoint: str,
    refresh_token: str,
    resource: str,
    credential: ClientCredential,
    scope: Optional[str] = None,
) -> TokenResponse:
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "resource": resource,
    }
    if scope:
        form["scope"] = scope
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    status, payload = await _post_form(token_endpoint, form, headers)
    _raise_for_error(status, payload, "Token refresh")
    return _token_response(payload, datetime.now(timezone.utc))


async def client_credentials_grant(
    *,
    token_endpoint: str,
    resource: str,
    credential: ClientCredential,
    scope: Optional[str] = None,
) -> TokenResponse:
    form = {"grant_type": "client_credentials", "resource": resource}
    if scope:
        form["scope"] = scope
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    status, payload = await _post_form(token_endpoint, form, headers)
    _raise_for_error(status, payload, "Client credentials grant")
    return _token_response(payload, datetime.now(timezone.utc))


async def revoke_token(
    *, revocation_endpoint: str, token: str, credential: ClientCredential
) -> None:
    """Best effort RFC 7009 revocation; failures are logged, never raised."""
    form = {"token": token}
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    try:
        status, _ = await _post_form(revocation_endpoint, form, headers)
    except OAuthTokenError as exc:
        logger.info("Token revocation at %s skipped: %s", revocation_endpoint, exc)
        return
    if status >= 400:
        logger.info(
            "Token revocation at %s answered HTTP %s", revocation_endpoint, status
        )


async def register_client(
    *, registration_endpoint: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """RFC 7591 Dynamic Client Registration; returns the server's response."""
    try:
        async with _client() as http:
            response = await http.post(
                registration_endpoint,
                content=json.dumps(metadata),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise OAuthTokenError(
            f"Registration endpoint unreachable: {exc}", status_code=0
        ) from exc
    try:
        payload: object = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    typed = cast(dict[str, Any], payload)
    _raise_for_error(response.status_code, typed, "Dynamic client registration")
    client_id = typed.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise OAuthTokenError(
            "Registration response carried no client_id",
            status_code=response.status_code,
        )
    return typed


# -- ID-JAG (Enterprise-Managed Authorization) --------------------------------


def peek_jwt_claim(token: str, claim: str) -> object:
    """Read one payload claim without verifying the signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload: object = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload).get(claim)


def peek_jwt_typ(token: str) -> Optional[str]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64 = parts[0] + "=" * (-len(parts[0]) % 4)
        header: object = json.loads(base64.urlsafe_b64decode(header_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(header, dict):
        return None
    typ = cast(dict[str, object], header).get("typ")
    return typ if isinstance(typ, str) else None


async def request_id_jag(
    *,
    idp_token_endpoint: str,
    id_token: str,
    authorization_server_issuer: str,
    resource: str,
    credential: ClientCredential,
    scope: Optional[str] = None,
) -> str:
    """Leg 1: exchange the login ID token for an ID-JAG at the enterprise IdP.

    ``audience`` MUST be the issuer of the MCP server's authorization server;
    ``resource`` names the MCP server. The IdP evaluates its policy here and
    answers with a signed assertion whose JOSE ``typ`` is ``oauth-id-jag+jwt``.
    """
    form = {
        "grant_type": TOKEN_EXCHANGE_GRANT,
        "requested_token_type": ID_JAG_TOKEN_TYPE,
        "subject_token": id_token,
        "subject_token_type": ID_TOKEN_TYPE,
        "audience": authorization_server_issuer,
        "resource": resource,
    }
    if scope:
        form["scope"] = scope
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    status, payload = await _post_form(idp_token_endpoint, form, headers)
    _raise_for_error(status, payload, "ID-JAG request")
    issued_type = payload.get("issued_token_type")
    if isinstance(issued_type, str) and issued_type != ID_JAG_TOKEN_TYPE:
        raise OAuthTokenError(
            f"IdP issued {issued_type!r}, expected {ID_JAG_TOKEN_TYPE!r}",
            status_code=status,
        )
    assertion = payload.get("access_token")
    if not isinstance(assertion, str) or not assertion:
        raise OAuthTokenError(
            "ID-JAG response carried no assertion", status_code=status
        )
    if peek_jwt_typ(assertion) != ID_JAG_JWT_TYP:
        # A plain ID or access token here would be replayable at the AS.
        raise OAuthTokenError(
            f"IdP returned an assertion of type {peek_jwt_typ(assertion)!r}, "
            f"expected {ID_JAG_JWT_TYP!r}",
            status_code=status,
        )
    return assertion


async def redeem_id_jag(
    *,
    token_endpoint: str,
    assertion: str,
    resource: str,
    credential: ClientCredential,
    scope: Optional[str] = None,
) -> TokenResponse:
    """Leg 2: present the ID-JAG at the MCP server's authorization server."""
    form = {
        "grant_type": JWT_BEARER_GRANT,
        "assertion": assertion,
        "resource": resource,
    }
    if scope:
        form["scope"] = scope
    headers: dict[str, str] = {}
    _apply_client_auth(form, headers, credential)
    status, payload = await _post_form(token_endpoint, form, headers)
    _raise_for_error(status, payload, "ID-JAG redemption")
    return _token_response(payload, datetime.now(timezone.utc))
