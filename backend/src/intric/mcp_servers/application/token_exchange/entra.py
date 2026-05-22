"""Entra ID — On-Behalf-Of flow.

Entra ID (Azure AD) does not implement RFC 8693 directly. Its delegated
access pattern is OBO, which uses the older ``jwt-bearer`` grant with an
explicit ``requested_token_use`` discriminator:

::

    POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=<user_access_token>
    requested_token_use=on_behalf_of
    scope=<api_scope>           # e.g. api://<mcp-app-id>/.default
    client_id=<broker_client_id>
    client_secret=<broker_client_secret>

The MCP server's canonical URI is *not* a meaningful Entra audience —
the broker must be configured with the target API's ``scope`` URI via
``MCPServer.target_resource_or_scope``. Missing scope is a configuration
error, not a runtime IdP failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from intric.mcp_servers.application.token_exchange import (
    ExchangedToken,
    IdpKind,
    TokenExchangeError,
    TokenExchangeStrategy,
    TokenExchangeTarget,
    classify_error,
    decode_expires_at,
    post_form,
)


class EntraOboStrategy(TokenExchangeStrategy):
    idp_kind: IdpKind = "entra"

    async def exchange(
        self,
        *,
        subject_access_token: str,
        target: TokenExchangeTarget,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
    ) -> ExchangedToken:
        if not target.resource_or_scope:
            raise TokenExchangeError(
                "Entra OBO requires target_resource_or_scope (the API scope URI, "
                "e.g. api://<mcp-app-id>/.default); none configured on the MCP server"
            )

        form: dict[str, str] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": subject_access_token,
            "requested_token_use": "on_behalf_of",
            "scope": target.resource_or_scope,
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
                "Entra returned 2xx without an access_token in the body"
            )

        scope = payload.get("scope")
        return ExchangedToken(
            access_token=access_token,
            expires_at=decode_expires_at(payload, now),
            issued_at=now,
            scope=str(scope) if isinstance(scope, str) else None,
        )
