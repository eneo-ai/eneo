"""The public keys a calling installation signs its assertions with.

Read from the address the administrator registered for the installation, never
from an address a token names (no ``jku``, no ``x5u``): that address is the
trust anchor. Kept in this process for a minute per installation. An assertion
naming a key that is not among them asks again, at most once a second, so a
rotated key is picked up at once and a made-up ``kid`` cannot be turned into a
stream of requests.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, cast

from eneo.authentication.oidc import outbound
from eneo.connector_protocol.installation import KEYS_PATH
from eneo.main.logging import get_logger

logger = get_logger(__name__)

KEYS_TTL_SECONDS = 60
UNKNOWN_KEY_REFETCH_SECONDS = 1


@dataclass
class _Entry:
    keys: dict[str, Any] | None = None
    until: float = 0.0
    last_fetch: float = float("-inf")
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_entries: dict[str, _Entry] = {}


def _knows(keys: dict[str, Any] | None, kid: str) -> bool:
    listed = keys.get("keys") if keys else None
    if not isinstance(listed, list):
        return False
    return any(
        isinstance(key, dict) and cast(dict[str, Any], key).get("kid") == kid
        for key in cast(list[object], listed)
    )


async def installation_keys(base_url: str, kid: str) -> dict[str, Any] | None:
    """The installation's key set, or None when it cannot be read."""
    entry = _entries.setdefault(base_url, _Entry())
    async with entry.lock:
        now = time.monotonic()
        stale = entry.keys is None or now >= entry.until
        unknown = not _knows(entry.keys, kid)
        if stale or (unknown and now - entry.last_fetch >= UNKNOWN_KEY_REFETCH_SECONDS):
            entry.last_fetch = now
            try:
                entry.keys = await outbound.get_json(base_url + KEYS_PATH)
                entry.until = time.monotonic() + KEYS_TTL_SECONDS
            except outbound.OidcFetchError as exc:
                # A fixed reason: it names no address and repeats no answer.
                logger.warning(
                    "Could not read a calling installation's keys",
                    extra={"reason": exc.reason, "status": exc.status},
                )
                if stale:
                    entry.keys = None
                    return None
        return entry.keys


def reset_installation_keys() -> None:
    """Forget every cached key set (a test hook)."""
    _entries.clear()
