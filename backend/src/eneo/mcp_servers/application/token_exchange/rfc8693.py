"""RFC 8693 Token Exchange: single-step same-IdP flow.

Covers Keycloak and any conformant IdP. The wire is the same regardless
of vendor: the spec defines
``grant_type=urn:ietf:params:oauth:grant-type:token-exchange`` with a
``subject_token`` of type ``access_token`` and a target identifier
expressed as ``audience`` (RFC 8693) and ``resource`` (RFC 8707). We
send both; conformant IdPs accept either.

::

    POST {token_endpoint}
    Content-Type: application/x-www-form-urlencoded

    grant_type=urn:ietf:params:oauth:grant-type:token-exchange
    subject_token=<user_access_token>
    subject_token_type=urn:ietf:params:oauth:token-type:access_token
    audience=<target>
    resource=<target>
    requested_token_type=urn:ietf:params:oauth:token-type:refresh_token
    client_id=<broker_client_id>
    client_secret=<broker_client_secret>

``requested_token_type=refresh_token`` asks the IdP to return a
refreshable pair so the broker can renew the audience token without
re-running the exchange. IdPs that ignore it still work; MCP access is
then capped at the main login token lifetime.
"""

from __future__ import annotations

import base64
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from eneo.mcp_servers.application.token_exchange import (
    ConcreteExchangeProtocol,
    ExchangedToken,
    TokenExchangeError,
    TokenExchangeStrategy,
    TokenExchangeTarget,
    classify_error,
    decode_expires_at,
    post_form,
)

logger = logging.getLogger(__name__)


def _peek_jwt_claims(token: str) -> dict[str, Any] | None:
    """Read JWT claims without signature verification for local sanity checks."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims: dict[str, Any] = _json.loads(base64.urlsafe_b64decode(payload_b64))
        return claims
    except Exception:
        return None


def peek_jwt_exp(token: str) -> datetime | None:
    """Read the ``exp`` claim from a JWT without signature verification."""
    claims = _peek_jwt_claims(token)
    if claims is not None:
        exp = claims.get("exp")
        if isinstance(exp, (int, float)):
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    return None


def _claim_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return expected in {str(item) for item in cast("list[Any]", value)}
    return False


def validate_exchanged_token_claims(
    *,
    access_token: str,
    subject_access_token: Optional[str],
    effective_audience: str,
    idp_issuer: Optional[str],
    now: datetime,
) -> datetime | None:
    """Reject obvious token-exchange failures before a token reaches an MCP server.

    This is not a replacement for full JWT verification by the MCP resource
    server. It prevents the broker from forwarding the caller's original IdP
    access token, and checks issuer/audience on JWTs when those claims are
    locally inspectable. Opaque tokens are allowed through.
    """
    if subject_access_token is not None and access_token == subject_access_token:
        raise TokenExchangeError(
            "IdP returned the subject access token unchanged; refusing to "
            "forward a user IdP token to the MCP server"
        )

    claims = _peek_jwt_claims(access_token)
    if claims is None:
        return None

    raw_exp = claims.get("exp")
    jwt_exp = (
        datetime.fromtimestamp(raw_exp, tz=timezone.utc)
        if isinstance(raw_exp, (int, float))
        else None
    )
    if jwt_exp is not None and jwt_exp <= now:
        raise TokenExchangeError(
            f"IdP returned a token whose exp claim ({jwt_exp.isoformat()}) "
            f"is already past (now={now.isoformat()})"
        )

    issuer = claims.get("iss")
    if idp_issuer and isinstance(issuer, str):
        if issuer.rstrip("/") != idp_issuer.rstrip("/"):
            raise TokenExchangeError(
                "IdP returned an exchanged token with unexpected issuer"
            )

    audience = claims.get("aud")
    if audience is not None and not _claim_contains(audience, effective_audience):
        raise TokenExchangeError(
            "IdP returned an exchanged token with unexpected audience"
        )

    return jwt_exp


class Rfc8693Strategy(TokenExchangeStrategy):
    """RFC 8693 token exchange; works with any OIDC + RFC 8693 conformant IdP."""

    exchange_protocol: ConcreteExchangeProtocol = "rfc8693"

    async def exchange(
        self,
        *,
        subject_access_token: str,
        target: TokenExchangeTarget,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
        idp_issuer: Optional[str] = None,
        subject_id_token: Optional[str] = None,
        as_issuer: Optional[str] = None,
        as_token_endpoint: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> ExchangedToken:
        # An override (per-server or tenant default) drives both the audience
        # and resource parameters so a shared-audience configuration flows
        # through. Without an override, both fall back to the MCP server's
        # RFC 8707 canonical resource (the PRM ``resource`` field).
        effective = target.resource_or_scope or target.audience
        form: dict[str, str] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_access_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": effective,
            "resource": effective,
            "requested_token_type": "urn:ietf:params:oauth:token-type:refresh_token",
            "client_id": client_id,
        }
        if client_secret:
            form["client_secret"] = client_secret

        subject_exp = peek_jwt_exp(subject_access_token)
        now = datetime.now(timezone.utc)
        status_code, payload = await post_form(token_endpoint=token_endpoint, form=form)
        if status_code >= 400:
            raise classify_error(status_code, payload)

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExchangeError(
                "RFC 8693 token exchange returned 2xx without an access_token"
            )

        raw_expires_in = payload.get("expires_in")
        jwt_exp = peek_jwt_exp(access_token)
        expires_at = decode_expires_at(payload, now)
        same_token = access_token == subject_access_token
        raw_refresh_token = payload.get("refresh_token")
        refresh_token = (
            raw_refresh_token
            if isinstance(raw_refresh_token, str) and raw_refresh_token
            else None
        )
        logger.info(
            "RFC 8693 exchange: audience=%s expires_in=%r "
            "subject_exp=%s exchanged_exp=%s same_token=%s "
            "now=%s token_type=%s has_refresh_token=%s "
            "granted_scope=%s",
            effective,
            raw_expires_in,
            subject_exp.isoformat() if subject_exp else None,
            jwt_exp.isoformat() if jwt_exp else None,
            same_token,
            now.isoformat(),
            payload.get("token_type"),
            refresh_token is not None,
            payload.get("scope"),
        )
        if refresh_token is None:
            logger.warning(
                "RFC 8693 exchange requested a refresh token for audience=%s "
                "but the IdP response did not include one; MCP access will "
                "fall back to the main login token lifetime",
                effective,
            )

        try:
            jwt_exp = validate_exchanged_token_claims(
                access_token=access_token,
                subject_access_token=subject_access_token,
                effective_audience=effective,
                idp_issuer=idp_issuer,
                now=now,
            )
        except TokenExchangeError:
            if refresh_token is None:
                raise
            jwt_exp = peek_jwt_exp(access_token)
            if jwt_exp is not None and jwt_exp <= now:
                logger.warning(
                    "RFC 8693 exchange returned expired access_token "
                    "(exp=%s, now=%s) but includes a refresh_token; "
                    "broker will refresh immediately (audience=%s)",
                    jwt_exp.isoformat(),
                    now.isoformat(),
                    effective,
                )
            else:
                raise

        if jwt_exp is not None:
            expires_at = jwt_exp
        elif expires_at <= now:
            logger.warning(
                "RFC 8693 exchange returned non-positive expires_in=%r; "
                "using 5-minute fallback (audience=%s)",
                raw_expires_in,
                effective,
            )
            expires_at = now + timedelta(minutes=5)

        scope = payload.get("scope")
        return ExchangedToken(
            access_token=access_token,
            expires_at=expires_at,
            issued_at=now,
            scope=str(scope) if isinstance(scope, str) else None,
            refresh_token=refresh_token,
        )
