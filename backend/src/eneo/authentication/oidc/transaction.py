"""The server-side sign-in transaction: single use, in Redis, never in the state.

The signed ``state`` names the transaction; the nonce and the PKCE verifier
live only here, so the browser and the provider never see the verifier. It
also keeps the issuer the request was sent to and whether that provider
announced RFC 9207, so a later config or discovery change cannot alter what
the callback accepts.

It also names its redeemer: the channel that started it and, when bound, the
S256 hash of a secret only the starting client holds. A leaked code and state
are then useless without that secret, and the backend cookie flow's
transactions are never redeemed through the bearer-token API.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from typing import Literal, TypeVar

from redis.asyncio import Redis

from eneo.authentication.oidc.errors import (
    OidcLoginUnavailableError,
    OidcTransactionInvalidError,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

_KEY = "oidc:transaction:{}"
# Redis answers in milliseconds. The shared pool sets no command timeout, so a
# connection that stops answering would otherwise hold a sign-in forever.
STORE_TIMEOUT_SECONDS = 2.0

# "api": POST /auth/callback answers with a bearer token. "browser": the
# backend's cookie callback, which answers with an HttpOnly session.
OidcChannel = Literal["api", "browser"]


def code_challenge(code_verifier: str) -> str:
    """The PKCE S256 challenge of a verifier (RFC 7636 4.2)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OidcTransaction:
    id: str
    purpose: Literal["login"]
    nonce: str
    code_verifier: str
    redirect_uri: str
    tenant_id: str
    tenant_slug: str
    config_version: str | None
    issued_at: int
    issuer: str
    iss_parameter_supported: bool
    channel: OidcChannel
    # S256 of the starting client's binding secret; None when unbound.
    binding_challenge: str | None

    @classmethod
    def start(
        cls,
        purpose: Literal["login"],
        *,
        channel: OidcChannel,
        binding_challenge: str | None,
        redirect_uri: str,
        tenant_id: str,
        tenant_slug: str,
        config_version: str | None,
        issuer: str,
        iss_parameter_supported: bool,
    ) -> "OidcTransaction":
        if channel == "browser" and binding_challenge is None:
            raise ValueError("A browser sign-in is always bound to its cookie.")
        return cls(
            id=secrets.token_urlsafe(32),
            purpose=purpose,
            nonce=secrets.token_urlsafe(32),
            # 86 characters of the unreserved alphabet (RFC 7636 4.1).
            code_verifier=secrets.token_urlsafe(64),
            redirect_uri=redirect_uri,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            config_version=config_version,
            issued_at=int(time.time()),
            issuer=issuer,
            iss_parameter_supported=iss_parameter_supported,
            channel=channel,
            binding_challenge=binding_challenge,
        )


async def save_transaction(
    store: Redis | None, transaction: OidcTransaction, *, ttl_seconds: int
) -> None:
    if store is None:
        raise OidcLoginUnavailableError()
    await _call(
        store.setex(
            _KEY.format(transaction.id),
            ttl_seconds,
            json.dumps(asdict(transaction), separators=(",", ":")),
        ),
        operation="save",
    )


async def take_transaction(
    store: Redis | None,
    transaction_id: str,
    *,
    channel: OidcChannel,
    binding_verifier: str | None,
) -> OidcTransaction:
    """Remove and return the transaction, for its redeemer only.

    The record is read first and checked against the channel and binding
    verifier; a refusal leaves it in place, so a holder of a leaked state
    cannot use up the owner's sign-in. GETDEL then admits exactly one
    callback: success rests only on what it returned.
    """
    if store is None:
        raise OidcLoginUnavailableError()
    key = _KEY.format(transaction_id)
    raw = await _call(store.get(key), operation="read")
    transaction = _parse(raw)
    refusal = _refusal(transaction, channel, binding_verifier)
    if refusal:
        logger.warning("oidc_transaction_refused", extra={"reason": refusal})
        raise OidcTransactionInvalidError()
    # Nothing writes the transaction back after a failed GETDEL: one that ran
    # but whose reply was lost leaves it used, one that did not run leaves it
    # for a later callback.
    if await _call(store.getdel(key), operation="take") != raw:
        raise OidcTransactionInvalidError()
    return transaction


async def _call(command: Awaitable[T], *, operation: str) -> T:
    try:
        async with asyncio.timeout(STORE_TIMEOUT_SECONDS):
            return await command
    # TimeoutError included; a caller's cancellation is not an Exception and
    # passes through.
    except Exception as exc:
        logger.error(
            "oidc_transaction_store_failed",
            extra={"operation": operation, "error_type": type(exc).__name__},
        )
        raise OidcLoginUnavailableError() from exc


def _parse(raw: object) -> OidcTransaction:
    if not isinstance(raw, str | bytes) or not raw:
        raise OidcTransactionInvalidError()
    # One written before a field existed fails here too; it never falls back.
    try:
        return OidcTransaction(**json.loads(raw))
    except (TypeError, ValueError) as exc:
        raise OidcTransactionInvalidError() from exc


def _refusal(
    transaction: OidcTransaction, channel: OidcChannel, binding_verifier: str | None
) -> str | None:
    if transaction.channel != channel:
        return "channel_mismatch"
    if transaction.binding_challenge is None:
        return "binding_unexpected" if binding_verifier is not None else None
    if binding_verifier is None:
        return "binding_missing"
    if not hmac.compare_digest(
        code_challenge(binding_verifier), transaction.binding_challenge
    ):
        return "binding_mismatch"
    return None
