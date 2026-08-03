"""Token-exchange strategies for the MCP OAuth token broker.

The MCP spec mandates ``Authorization: Bearer <token>`` audienced via
RFC 8707 to the target MCP server. To get that token without a second
user consent, the broker performs a delegated grant against the user's
existing IdP. Two wire formats are supported:

- ``rfc8693``: single-step same-IdP token exchange
  (``grant_type=urn:ietf:params:oauth:grant-type:token-exchange`` with
  the user's IdP access token as subject). Requires the MCP server's
  authorization server to be the tenant IdP itself.
- ``id_jag``: the MCP Enterprise-Managed Authorization flow. Step one
  exchanges the user's ID token for an Identity Assertion Authorization
  Grant at the IdP; step two presents that assertion to the MCP server's
  own authorization server via the RFC 7523 ``jwt-bearer`` grant.

``exchange_protocol`` on the MCP server row also allows ``auto``: the
broker resolves the concrete protocol from authorization-server metadata
(the ``id-jag`` grant profile) before calling :func:`resolve_strategy`,
which only accepts concrete protocols.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

import aiohttp

# Configured value on the MCP server row. ``auto`` is resolved by the
# broker to one of the concrete protocols before strategy lookup.
ExchangeProtocol = Literal["auto", "id_jag", "rfc8693"]
ConcreteExchangeProtocol = Literal["id_jag", "rfc8693"]
TOKEN_ENDPOINT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class TokenExchangeTarget:
    """What the broker is exchanging for: audience + optional override.

    ``audience`` is the canonical URI of the MCP server (RFC 8707) and
    becomes both the ``audience`` and ``resource`` parameters in the
    RFC 8693 form. ``resource_or_scope`` overrides both when set, for
    operators who federate a single MCP server under a shared audience
    or scope.
    """

    audience: str
    resource_or_scope: Optional[str] = None


@dataclass(frozen=True)
class ExchangedToken:
    """Result of a successful token-exchange call."""

    access_token: str
    expires_at: datetime
    issued_at: datetime
    scope: Optional[str]
    refresh_token: Optional[str] = None


class TokenExchangeError(Exception):
    """Strategy / IdP returned a non-2xx response that is not a user-fixable
    misconfiguration. The broker surfaces this as 502 to the caller."""


class TokenExchangeUserActionRequired(Exception):
    """The IdP rejected the subject token (e.g. invalid_grant). The caller
    must re-authenticate; the broker maps this to 401 with a clear remedy."""


class TokenExchangeStrategy(ABC):
    """Strategy interface. One concrete subclass per wire format."""

    exchange_protocol: ConcreteExchangeProtocol

    @abstractmethod
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
        """Perform the strategy-specific grant.

        ``subject_access_token`` is the user's IdP access token (or a tenant
        service-account access token for ``per_tenant`` flows). The ID-JAG
        strategy instead consumes ``subject_id_token`` plus the MCP server's
        authorization-server coordinates (``as_issuer`` /
        ``as_token_endpoint``); the same-IdP strategy ignores those.
        """
        ...


def decode_expires_at(payload: dict[str, Any], now: datetime) -> datetime:
    """Translate an ``expires_in`` integer (seconds) into a TZ-aware datetime.

    Falls back to a conservative 5-minute lifetime when the IdP omits the
    field or returns a non-positive value (Keycloak's RFC 8693 token exchange
    can return negative ``expires_in`` when computing remaining lifetime from
    the original session rather than minting a fresh TTL).
    """
    fallback = now + timedelta(minutes=5)
    raw = payload.get("expires_in")
    if isinstance(raw, (int, float)) and int(raw) > 0:
        return now + timedelta(seconds=int(raw))
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return now + timedelta(seconds=int(raw))
    return fallback


async def post_form(
    *, token_endpoint: str, form: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """Helper: POST ``application/x-www-form-urlencoded``, return ``(status, json)``."""
    timeout = aiohttp.ClientTimeout(total=TOKEN_ENDPOINT_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(
            token_endpoint,
            data=form,
            allow_redirects=False,
        ) as resp:
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


from eneo.mcp_servers.application.token_exchange.id_jag import (  # noqa: E402
    IdJagStrategy,
)
from eneo.mcp_servers.application.token_exchange.rfc8693 import (  # noqa: E402
    Rfc8693Strategy,
)

__all__ = [
    "ConcreteExchangeProtocol",
    "ExchangeProtocol",
    "ExchangedToken",
    "IdJagStrategy",
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


def resolve_strategy(protocol: ConcreteExchangeProtocol) -> TokenExchangeStrategy:
    """Look up the strategy for a concrete exchange protocol.

    ``auto`` never reaches this function: the broker resolves it against
    authorization-server metadata first.
    """
    if protocol == "rfc8693":
        return Rfc8693Strategy()
    if protocol == "id_jag":
        return IdJagStrategy()
    raise ValueError(f"Unsupported exchange_protocol: {protocol}")
