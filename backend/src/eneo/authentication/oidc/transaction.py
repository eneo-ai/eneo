"""The server-side sign-in transaction: single use, in Redis, never in the state.

The signed ``state`` names the transaction; the nonce and the PKCE verifier
live only here, so the browser and the provider never see the verifier. It
also keeps the issuer the request was sent to and whether that provider
announced RFC 9207, so a later config or discovery change cannot alter what
the callback accepts.
"""

import asyncio
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Literal

from redis.asyncio import Redis

from eneo.authentication.oidc.errors import (
    OidcLoginUnavailableError,
    OidcTransactionInvalidError,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_KEY = "oidc:transaction:{}"
# Redis answers in milliseconds. The shared pool sets no command timeout, so a
# connection that stops answering would otherwise hold a sign-in forever.
STORE_TIMEOUT_SECONDS = 2.0


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

    @classmethod
    def start(
        cls,
        purpose: Literal["login"],
        *,
        redirect_uri: str,
        tenant_id: str,
        tenant_slug: str,
        config_version: str | None,
        issuer: str,
        iss_parameter_supported: bool,
    ) -> "OidcTransaction":
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
        )


async def save_transaction(
    store: Redis | None, transaction: OidcTransaction, *, ttl_seconds: int
) -> None:
    if store is None:
        raise OidcLoginUnavailableError()
    try:
        async with asyncio.timeout(STORE_TIMEOUT_SECONDS):
            await store.setex(
                _KEY.format(transaction.id),
                ttl_seconds,
                json.dumps(asdict(transaction), separators=(",", ":")),
            )
    # TimeoutError included; a caller's cancellation is not an Exception and
    # passes through.
    except Exception as exc:
        logger.error(
            "oidc_transaction_store_failed",
            extra={"operation": "save", "error_type": type(exc).__name__},
        )
        raise OidcLoginUnavailableError() from exc


async def take_transaction(store: Redis | None, transaction_id: str) -> OidcTransaction:
    """Remove and return the transaction; GETDEL admits exactly one callback."""
    if store is None:
        raise OidcLoginUnavailableError()
    try:
        # A GETDEL that timed out may still have run, so the transaction then
        # counts as used: nothing ever writes it back.
        async with asyncio.timeout(STORE_TIMEOUT_SECONDS):
            raw = await store.getdel(_KEY.format(transaction_id))
    except Exception as exc:
        logger.error(
            "oidc_transaction_store_failed",
            extra={"operation": "take", "error_type": type(exc).__name__},
        )
        raise OidcLoginUnavailableError() from exc
    if not isinstance(raw, str | bytes) or not raw:
        raise OidcTransactionInvalidError()
    # One written before a field existed fails here too; it never falls back.
    try:
        return OidcTransaction(**json.loads(raw))
    except (TypeError, ValueError) as exc:
        raise OidcTransactionInvalidError() from exc
