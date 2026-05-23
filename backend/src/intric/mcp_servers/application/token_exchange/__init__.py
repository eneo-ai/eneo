"""Token-exchange strategy for the same-IdP MCP OAuth broker.

The MCP 2025-11-25 spec mandates ``Authorization: Bearer <token>`` audienced
via RFC 8707 to the target MCP server. To get that token without a second
user consent, the broker performs a delegated grant against the user's
existing IdP. Eneo standardises on RFC 8693 token-exchange
(``grant_type=urn:ietf:params:oauth:grant-type:token-exchange``); any
OIDC + RFC 8693 conformant IdP works without additional code.

A single-value ``ExchangeProtocol`` literal is preserved so that adding a
second wire format later (e.g. legacy Entra OBO via ``jwt-bearer``) is
purely additive: implement another :class:`TokenExchangeStrategy`, add a
literal value, branch in :func:`resolve_strategy`. No structural refactor
required at the call sites.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

import aiohttp

# Wire-format discriminator. Currently single-valued; future protocols
# (e.g. ``"jwt_bearer_obo"`` for legacy Entra OBO) extend this literal and
# add a branch in :func:`resolve_strategy`.
ExchangeProtocol = Literal["rfc8693"]


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


class TokenExchangeError(Exception):
    """Strategy / IdP returned a non-2xx response that is not a user-fixable
    misconfiguration. The broker surfaces this as 502 to the caller."""


class TokenExchangeUserActionRequired(Exception):
    """The IdP rejected the subject token (e.g. invalid_grant). The caller
    must re-authenticate; the broker maps this to 401 with a clear remedy."""


class TokenExchangeStrategy(ABC):
    """Strategy interface. One concrete subclass per IdP wire format."""

    exchange_protocol: ExchangeProtocol

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


from intric.mcp_servers.application.token_exchange.rfc8693 import Rfc8693Strategy

__all__ = [
    "ExchangeProtocol",
    "ExchangedToken",
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


def resolve_strategy(protocol: ExchangeProtocol) -> TokenExchangeStrategy:
    """Look up the strategy for the configured exchange protocol.

    Today RFC 8693 is the only supported wire format. The branch shape is
    preserved so that adding a second protocol (e.g. legacy Entra OBO) is
    a one-line change here plus a new strategy file.
    """
    if protocol == "rfc8693":
        return Rfc8693Strategy()
    raise ValueError(f"Unsupported exchange_protocol: {protocol}")
