"""Token-exchange strategies for the same-IdP MCP OAuth broker.

The MCP 2025-11-25 spec mandates ``Authorization: Bearer <token>`` audienced
via RFC 8707 to the target MCP server. To get that token without a second
user consent, the broker performs a delegated grant against the user's
existing IdP. Only two wire formats are in play:

- **RFC 8693 token-exchange** (``grant_type=urn:ietf:params:oauth:grant-type:token-exchange``).
  Covers Keycloak and any conformant IdP. The strategy sends both
  ``audience`` and ``resource`` per RFC 8693 + RFC 8707.
- **Entra ID On-Behalf-Of** (``grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer``
  + ``requested_token_use=on_behalf_of``). Entra does not implement
  RFC 8693 directly.

The :class:`TokenExchangeStrategy` interface hides the wire format from
the broker. ``IdpKind`` discriminates which implementation to dispatch
based on the tenant's ``federation_config.idp_kind``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

import aiohttp

IdpKind = Literal["keycloak", "entra"]


@dataclass(frozen=True)
class TokenExchangeTarget:
    """What the broker is exchanging for: audience + scope hint."""

    # Canonical URI of the MCP server (RFC 8707). Keycloak uses this as
    # both ``audience`` and ``resource``; Entra ignores it in favour of
    # ``scope``.
    audience: str
    # Strategy-specific override. For Keycloak this becomes ``resource``;
    # for Entra it becomes the API ``scope`` (e.g.
    # ``api://<mcp-app-id>/.default``). When ``None`` the strategy falls
    # back to ``audience`` (Keycloak) or refuses (Entra).
    resource_or_scope: Optional[str] = None


@dataclass(frozen=True)
class ExchangedToken:
    """Result of a successful token-exchange call."""

    access_token: str
    expires_at: datetime
    issued_at: datetime
    scope: Optional[str]


class TokenExchangeError(Exception):
    """Strategy / IdP returned a non-2xx response that is not a user-fixable
    misconfiguration. The broker surfaces this as 502 to the caller."""


class TokenExchangeUserActionRequired(Exception):
    """The IdP rejected the subject token (e.g. invalid_grant). The caller
    must re-authenticate; the broker maps this to 401 with a clear remedy."""


class TokenExchangeStrategy(ABC):
    """Strategy interface. One concrete subclass per IdP wire format."""

    idp_kind: IdpKind

    @abstractmethod
    async def exchange(
        self,
        *,
        subject_access_token: str,
        target: TokenExchangeTarget,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
    ) -> ExchangedToken:
        """Perform the strategy-specific grant against the IdP's token endpoint.

        ``subject_access_token`` is the user's IdP access token (or a tenant
        service-account access token for ``per_tenant`` flows; the wire
        differs only in subject acquisition, not the exchange grant).
        """
        ...


def decode_expires_at(payload: dict[str, Any], now: datetime) -> datetime:
    """Translate an ``expires_in`` integer (seconds) into a TZ-aware datetime.

    Falls back to a conservative 5-minute lifetime when the IdP omits the
    field; the broker subtracts a 60-second safety margin on top.
    """
    raw = payload.get("expires_in")
    if isinstance(raw, (int, float)):
        return now + timedelta(seconds=int(raw))
    if isinstance(raw, str) and raw.isdigit():
        return now + timedelta(seconds=int(raw))
    return now + timedelta(minutes=5)


async def post_form(
    *, token_endpoint: str, form: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """Helper: POST ``application/x-www-form-urlencoded`` and return ``(status, json)``."""
    async with aiohttp.ClientSession() as http:
        async with http.post(token_endpoint, data=form) as resp:
            text_body = await resp.text()
            payload: dict[str, Any]
            try:
                payload = json.loads(text_body) if text_body else {}
            except Exception:
                payload = {"raw": text_body}
            return resp.status, payload


def classify_error(status_code: int, payload: dict[str, Any]) -> Exception:
    """Translate IdP error responses into the broker's error vocabulary."""
    error_code = str(payload.get("error", "unknown_error"))
    description = str(payload.get("error_description", ""))
    if error_code in {"invalid_grant", "interaction_required", "login_required"}:
        return TokenExchangeUserActionRequired(
            f"IdP requires re-authentication ({error_code}): {description}"
        )
    return TokenExchangeError(
        f"IdP rejected token exchange: HTTP {status_code} {error_code} {description}"
    )


from intric.mcp_servers.application.token_exchange.entra import EntraOboStrategy
from intric.mcp_servers.application.token_exchange.rfc8693 import Rfc8693Strategy

__all__ = [
    "EntraOboStrategy",
    "ExchangedToken",
    "IdpKind",
    "Rfc8693Strategy",
    "TokenExchangeError",
    "TokenExchangeStrategy",
    "TokenExchangeTarget",
    "TokenExchangeUserActionRequired",
    "classify_error",
    "decode_expires_at",
    "post_form",
    "resolve_strategy",
]


def resolve_strategy(idp_kind: IdpKind) -> TokenExchangeStrategy:
    """Look up the strategy for a tenant's configured ``idp_kind``.

    Only two wire formats exist in practice: RFC 8693 (Keycloak and any
    conformant IdP) and Entra OBO. The ``keycloak`` value is the spelling
    operators recognise; it maps to the generic RFC 8693 implementation.
    """
    if idp_kind == "keycloak":
        return Rfc8693Strategy()
    if idp_kind == "entra":
        return EntraOboStrategy()
    raise ValueError(f"Unsupported idp_kind: {idp_kind}")
