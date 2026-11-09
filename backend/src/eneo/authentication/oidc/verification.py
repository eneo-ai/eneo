"""Turn the provider's authorization response into one verified authentication.

Every check of the response refuses with ``OidcResponseNotVerifiedError``, and
a sign-in whose provider changed after it started with
``OidcTransactionInvalidError``; nothing here falls back to a weaker check
when a stronger one fails.
"""

import base64
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import jwt

from eneo.authentication.auth_models import FederatedIdentity
from eneo.authentication.auth_service import OIDC_CLOCK_LEEWAY_SECONDS, AuthService
from eneo.authentication.oidc.errors import (
    OidcResponseNotVerifiedError,
    OidcTransactionInvalidError,
)
from eneo.authentication.oidc.profile import OidcProfile
from eneo.authentication.oidc.transaction import OidcTransaction
from eneo.authentication.oidc_resource_server import get_federation_signing_key
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_REQUIRED_CLAIMS = ["iss", "sub", "aud", "exp", "iat"]


@dataclass(frozen=True)
class CallbackResponse:
    """What the provider sent to the redirect URI."""

    code: str
    # RFC 9207 issuer identification, when the provider sends it.
    iss: str | None = None


@dataclass(frozen=True)
class VerifiedAuthentication:
    issuer: str
    client_id: str
    # The value of the profile's subject claim, ``sub`` by default.
    subject: str
    claims: Mapping[str, object]
    acr: str | None
    amr: tuple[str, ...] | None
    auth_time: int | None
    email_claim: str
    subject_claim: str
    email_verified_claims: tuple[str, ...]

    def identity(self) -> FederatedIdentity:
        """The email facts under the profile's claim mapping.

        Raises ValueError when the email is missing, invalid or explicitly
        unverified, as the admission has always done.
        """
        return FederatedIdentity.from_claims(
            self.claims,
            issuer=self.issuer,
            audience=self.client_id,
            subject_claim=self.subject_claim,
            email_claim=self.email_claim,
            email_verified_claims=self.email_verified_claims,
        )


def _refuse(
    reason: str,
    correlation_id: str,
    message: str = "The sign-in response could not be verified.",
) -> OidcResponseNotVerifiedError:
    logger.warning(
        "oidc_response_refused",
        extra={"reason": reason, "correlation_id": correlation_id},
    )
    return OidcResponseNotVerifiedError(message)


# An OAuth error code (RFC 6749 section 5.2) is a short token. What else a
# provider writes, its description, its URI or a body that is not JSON, can
# name the person signing in, so it is never logged.
_OAUTH_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _oauth_error(body: object) -> str | None:
    if not isinstance(body, Mapping):
        return None
    error = cast(Mapping[str, object], body).get("error")
    if isinstance(error, str) and _OAUTH_ERROR_CODE.fullmatch(error):
        return error
    return None


async def _exchange_code(
    profile: OidcProfile, transaction: OidcTransaction, code: str, correlation_id: str
) -> Mapping[str, object]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": transaction.redirect_uri,
        "code_verifier": transaction.code_verifier,
        "client_id": profile.client_id,
        "client_secret": profile.client_secret,
    }
    headers: dict[str, str] = {}
    if profile.token_endpoint_auth_method == "client_secret_basic":
        credentials = f"{profile.client_id}:{profile.client_secret}"
        headers["Authorization"] = (
            f"Basic {base64.b64encode(credentials.encode()).decode()}"
        )
        del data["client_id"], data["client_secret"]

    async with aiohttp_client().post(
        profile.token_endpoint, data=data, headers=headers or None
    ) as resp:
        if resp.status != 200:
            try:
                error_body: object = await resp.json()
            except Exception:
                error_body = None
            failure: dict[str, object] = {
                "http_status": resp.status,
                "token_endpoint": profile.token_endpoint,
                "auth_method": profile.token_endpoint_auth_method,
                "correlation_id": correlation_id,
            }
            if (oauth_error := _oauth_error(error_body)) is not None:
                failure["oauth_error"] = oauth_error
            logger.error(f"Token exchange failed: HTTP {resp.status}", extra=failure)
            raise _refuse(
                "token_exchange_failed",
                correlation_id,
                "Failed to exchange authorization code for tokens",
            )
        body: object = await resp.json()
    return cast(Mapping[str, object], body) if isinstance(body, Mapping) else {}


def _optional_number(claims: Mapping[str, object], name: str) -> int | float | None:
    value = claims.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(name)
    return value


async def verify_response(
    profile: OidcProfile,
    transaction: OidcTransaction,
    callback: CallbackResponse,
    *,
    jwks_ttl_seconds: int,
    correlation_id: str,
) -> VerifiedAuthentication:
    """Exchange the code (with the PKCE verifier) and verify the ID token.

    The issuer and RFC 9207 support come from the transaction, as they were
    when the request was sent; the profile supplies endpoints, keys and client.
    """
    if profile.issuer != transaction.issuer:
        # The provider changed during the sign-in: its code must not reach
        # another configuration's token endpoint.
        logger.warning(
            "oidc_transaction_refused",
            extra={"reason": "issuer_changed", "correlation_id": correlation_id},
        )
        raise OidcTransactionInvalidError()
    if callback.iss is not None:
        if callback.iss != transaction.issuer:
            raise _refuse("iss_parameter_mismatch", correlation_id)
    elif transaction.iss_parameter_supported:
        raise _refuse("iss_parameter_missing", correlation_id)

    tokens = await _exchange_code(profile, transaction, callback.code, correlation_id)
    id_token, access_token = tokens.get("id_token"), tokens.get("access_token")
    if not isinstance(id_token, str) or not isinstance(access_token, str):
        raise _refuse(
            "tokens_missing",
            correlation_id,
            "Missing id_token or access_token in response",
        )

    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError:
        raise _refuse("id_token_malformed", correlation_id) from None
    if header.get("alg") not in profile.signing_algorithms:
        raise _refuse("algorithm_not_allowed", correlation_id)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise _refuse("key_id_missing", correlation_id)
    try:
        signing_key = await get_federation_signing_key(
            issuer=profile.issuer,
            jwks_uri=profile.jwks_uri,
            kid=kid,
            ttl_seconds=jwks_ttl_seconds,
        )
    except Exception as exc:
        logger.error(
            "Failed to fetch JWKS or extract signing key",
            extra={
                "jwks_uri": profile.jwks_uri,
                "error_type": type(exc).__name__,
                "correlation_id": correlation_id,
            },
        )
        raise _refuse(
            "signing_key_unavailable",
            correlation_id,
            "Failed to validate ID token signature",
        ) from None

    try:
        # The raw key, so the header's algorithm (already limited to the
        # allowed ones) must also fit the key's type.
        claims: dict[str, Any] = AuthService().get_payload_from_openid_jwt(
            id_token=id_token,
            access_token=access_token,
            key=cast(jwt.PyJWK, signing_key.key),
            signing_algos=list(profile.signing_algorithms),
            client_id=profile.client_id,
            options={"require": _REQUIRED_CLAIMS},
            correlation_id=correlation_id,
        )
    except (jwt.PyJWTError, TypeError, ValueError):
        # PyJWT raises TypeError when the header's algorithm does not fit the
        # key's type, for example ES256 against an RSA key.
        raise _refuse("id_token_invalid", correlation_id) from None

    if claims.get("iss") != transaction.issuer:
        raise _refuse("issuer_mismatch", correlation_id)
    audience, azp = claims.get("aud"), claims.get("azp")
    if azp is not None and azp != profile.client_id:
        raise _refuse("azp_mismatch", correlation_id)
    if isinstance(audience, list) and len(cast(list[object], audience)) > 1:
        if azp is None:
            raise _refuse("azp_missing", correlation_id)
    nonce = claims.get("nonce")
    # As bytes: compare_digest refuses str with non-ASCII characters.
    if not isinstance(nonce, str) or not secrets.compare_digest(
        nonce.encode(), transaction.nonce.encode()
    ):
        raise _refuse("nonce_mismatch", correlation_id)
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise _refuse("subject_missing", correlation_id)
    # A configured subject claim is required in addition to sub.
    subject = claims.get(profile.subject_claim)
    if not isinstance(subject, str) or not subject:
        raise _refuse("subject_missing", correlation_id)

    try:
        auth_time = _optional_number(claims, "auth_time")
    except ValueError:
        raise _refuse("auth_time_invalid", correlation_id) from None
    if auth_time is not None and auth_time > time.time() + (
        OIDC_CLOCK_LEEWAY_SECONDS or 0
    ):
        raise _refuse("auth_time_in_future", correlation_id)

    acr = claims.get("acr")
    if acr is not None and not isinstance(acr, str):
        raise _refuse("acr_invalid", correlation_id)
    amr = claims.get("amr")
    if amr is not None and not (
        isinstance(amr, list)
        and all(isinstance(method, str) for method in cast(list[object], amr))
    ):
        raise _refuse("amr_invalid", correlation_id)

    return VerifiedAuthentication(
        issuer=transaction.issuer,
        client_id=profile.client_id,
        subject=subject,
        claims=claims,
        acr=acr,
        amr=tuple(cast(list[str], amr)) if amr is not None else None,
        auth_time=int(auth_time) if auth_time is not None else None,
        email_claim=profile.email_claim,
        subject_claim=profile.subject_claim,
        email_verified_claims=profile.email_verified_claims,
    )
