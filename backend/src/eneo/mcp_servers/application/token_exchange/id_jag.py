"""Identity Assertion Authorization Grant (ID-JAG): two-step enterprise flow.

Implements the MCP Enterprise-Managed Authorization extension. Unlike the
same-IdP RFC 8693 flow, the MCP server's authorization server may be a
third party; it only needs to trust the enterprise IdP's signing keys.

Leg 1, at the enterprise IdP token endpoint (policy decision point)::

    grant_type=urn:ietf:params:oauth:grant-type:token-exchange
    requested_token_type=urn:ietf:params:oauth:token-type:id-jag
    subject_token=<user ID token>
    subject_token_type=urn:ietf:params:oauth:token-type:id_token
    audience=<issuer of the MCP server's authorization server>
    resource=<MCP server resource identifier>
    scope=<requested scopes, when known>
    client_id=<federation client>  (+ client_secret, as during SSO)

The IdP evaluates administrator policy and returns a short-lived signed
assertion with JWT header ``typ: oauth-id-jag+jwt``.

Leg 2, at the MCP server's authorization server token endpoint::

    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=<ID-JAG>
    client_id=<federation client>

The AS validates the assertion against the IdP's JWKS and mints its own
access token, audience-restricted to the MCP resource. That token (plus
any refresh token) is what the broker caches and forwards.
"""

from __future__ import annotations

import base64
import json as _json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from eneo.main.logging import get_logger
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
from eneo.mcp_servers.application.token_exchange.rfc8693 import (
    peek_jwt_exp,
    validate_exchanged_token_claims,
)

logger = get_logger(__name__)

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ID_JAG_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id-jag"
ID_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
ID_JAG_JWT_TYP = "oauth-id-jag+jwt"


def peek_jwt_typ(token: str) -> Optional[str]:
    """Read the JOSE header ``typ`` without signature verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64 = parts[0]
        header_b64 += "=" * (-len(header_b64) % 4)
        header: dict[str, Any] = _json.loads(base64.urlsafe_b64decode(header_b64))
        typ = header.get("typ")
        return typ if isinstance(typ, str) else None
    except Exception:
        return None


class IdJagStrategy(TokenExchangeStrategy):
    """Two-leg ID-JAG exchange per the MCP Enterprise-Managed Authorization
    extension (draft-ietf-oauth-identity-assertion-authz-grant)."""

    exchange_protocol: ConcreteExchangeProtocol = "id_jag"

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
        """Run both legs and return the AS-minted access token.

        ``token_endpoint`` is the enterprise IdP's (leg 1);
        ``as_token_endpoint`` is the MCP server's AS (leg 2).
        ``subject_id_token`` is required: the identity assertion is the
        OIDC ID token, not the access token.
        """
        if not subject_id_token:
            raise TokenExchangeError(
                "ID-JAG exchange requires the user's stored ID token as the "
                "identity assertion; none was provided"
            )
        if not as_issuer or not as_token_endpoint:
            raise TokenExchangeError(
                "ID-JAG exchange requires the MCP server's authorization "
                "server issuer and token endpoint from discovery"
            )

        id_jag = await self._request_id_jag(
            idp_token_endpoint=token_endpoint,
            subject_id_token=subject_id_token,
            as_issuer=as_issuer,
            target=target,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        )
        return await self._redeem_id_jag(
            id_jag=id_jag,
            as_token_endpoint=as_token_endpoint,
            as_issuer=as_issuer,
            target=target,
            client_id=client_id,
        )

    async def _request_id_jag(
        self,
        *,
        idp_token_endpoint: str,
        subject_id_token: str,
        as_issuer: str,
        target: TokenExchangeTarget,
        client_id: str,
        client_secret: Optional[str],
        scope: Optional[str],
    ) -> str:
        effective = target.resource_or_scope or target.audience
        form: dict[str, str] = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "requested_token_type": ID_JAG_TOKEN_TYPE,
            "subject_token": subject_id_token,
            "subject_token_type": ID_TOKEN_TYPE,
            # Per the draft, audience MUST be the issuer identifier of the
            # resource authorization server; resource carries the MCP
            # server's resource identifier.
            "audience": as_issuer,
            "resource": effective,
            "client_id": client_id,
        }
        if scope:
            form["scope"] = scope
        if client_secret:
            form["client_secret"] = client_secret

        status_code, payload = await post_form(
            token_endpoint=idp_token_endpoint, form=form
        )
        if status_code >= 400:
            raise classify_error(status_code, payload)

        issued_token_type = payload.get("issued_token_type")
        id_jag = payload.get("access_token")
        if not isinstance(id_jag, str) or not id_jag:
            raise TokenExchangeError(
                "ID-JAG request returned 2xx without an assertion in access_token"
            )
        if (
            isinstance(issued_token_type, str)
            and issued_token_type != ID_JAG_TOKEN_TYPE
        ):
            raise TokenExchangeError(
                f"IdP issued token type {issued_token_type!r}, "
                f"expected {ID_JAG_TOKEN_TYPE!r}"
            )
        typ = peek_jwt_typ(id_jag)
        if typ != ID_JAG_JWT_TYP:
            # A plain ID/access token here would be replayable at the AS;
            # refusing on typ is the conformance tripwire.
            raise TokenExchangeError(
                f"IdP returned an assertion with JWT typ {typ!r}, "
                f"expected {ID_JAG_JWT_TYP!r}"
            )
        logger.info(
            "ID-JAG issued: audience=%s resource=%s",
            as_issuer,
            target.resource_or_scope or target.audience,
        )
        return id_jag

    async def _redeem_id_jag(
        self,
        *,
        id_jag: str,
        as_token_endpoint: str,
        as_issuer: str,
        target: TokenExchangeTarget,
        client_id: str,
    ) -> ExchangedToken:
        form = {
            "grant_type": JWT_BEARER_GRANT,
            "assertion": id_jag,
            "client_id": client_id,
        }
        now = datetime.now(timezone.utc)
        status_code, payload = await post_form(
            token_endpoint=as_token_endpoint, form=form
        )
        if status_code >= 400:
            raise classify_error(status_code, payload)

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExchangeError(
                "jwt-bearer redemption returned 2xx without an access_token"
            )

        raw_refresh_token = payload.get("refresh_token")
        refresh_token = (
            raw_refresh_token
            if isinstance(raw_refresh_token, str) and raw_refresh_token
            else None
        )
        effective = target.resource_or_scope or target.audience
        # The AS-minted token's issuer is the AS, not the enterprise IdP.
        jwt_exp = validate_exchanged_token_claims(
            access_token=access_token,
            subject_access_token=id_jag,
            effective_audience=effective,
            idp_issuer=as_issuer,
            now=now,
        )
        expires_at = jwt_exp or decode_expires_at(payload, now)
        if expires_at <= now:
            expires_at = now + timedelta(minutes=5)

        scope_value = payload.get("scope")
        logger.info(
            "ID-JAG redeemed at AS %s: audience=%s exp=%s has_refresh_token=%s",
            as_issuer,
            effective,
            expires_at.isoformat(),
            refresh_token is not None,
        )
        exp_peek = peek_jwt_exp(access_token)
        if exp_peek is not None and exp_peek < expires_at:
            expires_at = exp_peek
        return ExchangedToken(
            access_token=access_token,
            expires_at=expires_at,
            issued_at=now,
            scope=scope_value if isinstance(scope_value, str) else None,
            refresh_token=refresh_token,
        )
