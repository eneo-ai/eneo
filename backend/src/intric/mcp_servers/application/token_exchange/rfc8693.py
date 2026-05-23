"""RFC 8693 Token Exchange — covers Keycloak and any conformant IdP.

The wire is the same regardless of vendor: the spec defines
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
    requested_token_type=urn:ietf:params:oauth:token-type:access_token
    client_id=<broker_client_id>
    client_secret=<broker_client_secret>

Entra ID uses a different grant (OBO with ``jwt-bearer``) and lives in
its own module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from intric.mcp_servers.application.token_exchange import (
    ExchangedToken,
    ExchangeProtocol,
    TokenExchangeError,
    TokenExchangeStrategy,
    TokenExchangeTarget,
    classify_error,
    decode_expires_at,
    post_form,
)


class Rfc8693Strategy(TokenExchangeStrategy):
    """RFC 8693 token exchange — works with any OIDC + RFC 8693 conformant IdP."""

    exchange_protocol: ExchangeProtocol = "rfc8693"

    async def exchange(
        self,
        *,
        subject_access_token: str,
        target: TokenExchangeTarget,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
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
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "client_id": client_id,
        }
        if client_secret:
            form["client_secret"] = client_secret

        now = datetime.now(timezone.utc)
        status_code, payload = await post_form(token_endpoint=token_endpoint, form=form)
        if status_code >= 400:
            raise classify_error(status_code, payload)

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExchangeError(
                "RFC 8693 token exchange returned 2xx without an access_token"
            )

        scope = payload.get("scope")
        return ExchangedToken(
            access_token=access_token,
            expires_at=decode_expires_at(payload, now),
            issued_at=now,
            scope=str(scope) if isinstance(scope, str) else None,
        )
