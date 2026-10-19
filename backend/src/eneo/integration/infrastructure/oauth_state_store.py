"""Single-use OAuth ``state`` values, held in Redis until the callback redeems them.

The backend generates the state, binds it to the initiating principal in
Redis and requires the callback to echo it, which prevents login CSRF and
auth-code injection. Both OAuth flows (per-user connections and the admin's
service-account sign-in) use this store; they differ only in key prefix and
in whether the payload is sealed, which the admin flow needs because its
first sign-in carries the Entra client secret.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional, cast

from eneo.main.exceptions import EncryptionNotConfiguredException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from eneo.settings.encryption_service import EncryptionService

logger = get_logger(__name__)

OAUTH_STATE_TTL_SECONDS = 600


class OauthStateStore:
    def __init__(
        self,
        redis_client: "aioredis.Redis",
        *,
        prefix: str,
        ttl_seconds: int = OAUTH_STATE_TTL_SECONDS,
        encryption_service: Optional["EncryptionService"] = None,
    ) -> None:
        super().__init__()
        self.redis_client = redis_client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds
        self.encryption_service = encryption_service

    async def store(self, state: str, data: dict[str, str]) -> None:
        payload = json.dumps(data)
        if self.encryption_service is not None:
            payload = self.encryption_service.encrypt(payload)
        await self.redis_client.set(
            f"{self.prefix}{state}", payload, ex=self.ttl_seconds
        )

    async def peek(self, state: str) -> Optional[dict[str, str]]:
        """The bound data without spending the state, so a callback can check
        the binding first and a mismatched caller cannot burn another's state."""
        return self._decode(await self.redis_client.get(f"{self.prefix}{state}"))

    async def pop(self, state: str) -> Optional[dict[str, str]]:
        """The bound data, or None when the state is unknown, spent or unreadable."""
        # GETDEL makes the state single-use even under concurrent callbacks.
        return self._decode(await self.redis_client.getdel(f"{self.prefix}{state}"))

    def _decode(self, raw: object) -> Optional[dict[str, str]]:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            text = str(raw)
            if self.encryption_service is not None:
                text = self.encryption_service.decrypt(text)
            data = cast(object, json.loads(text))
        except (ValueError, TypeError, EncryptionNotConfiguredException):
            # Unreadable states are invalid states (a 400 for the caller),
            # not a 500.
            logger.warning("Discarding undecryptable or corrupt OAuth state")
            return None
        if not isinstance(data, dict):
            return None
        return cast(dict[str, str], data)
