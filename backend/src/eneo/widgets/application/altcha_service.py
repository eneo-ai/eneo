# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import hashlib
import time
from typing import Any, Optional, cast

import altcha
import redis.exceptions

from eneo.main.config import Settings, get_settings
from eneo.main.logging import get_logger
from eneo.widgets.domain.exceptions import (
    ChallengeInvalidError,
    WidgetProtectionUnavailableError,
)
from eneo.widgets.domain.widget import Widget

logger = get_logger(__name__)

# The altcha package ships untyped dicts; keep the boundary in one place.
_altcha: Any = altcha

ALGORITHM = "SHA-256"
_REPLAY_PREFIX = "widget:altcha:"


class AltchaService:
    """Self-hosted proof of work (ALTCHA v2).

    The challenge is HMAC-signed with a key derived from the deployment's
    signing secret and the widget, so it needs no storage and only the
    widget that issued it, under its own challenge limit, accepts it. A
    solved nonce is recorded in Redis for the challenge's remaining
    lifetime to stop replays. With ``widget_rate_limit_fail_open`` a Redis
    outage skips that replay check too, so the flag trades bot protection
    for availability, not only rate limits.
    """

    def __init__(self, redis_client: Any, settings: Optional[Settings] = None) -> None:
        self.redis = redis_client
        self.settings = settings or get_settings()

    def _secret(self, widget: Widget) -> str:
        assert widget.id is not None
        return hashlib.sha256(
            f"eneo-widget-altcha:{widget.id}:{self.settings.url_signing_key}".encode()
        ).hexdigest()

    def create_challenge(self, widget: Widget) -> dict[str, Any]:
        challenge = _altcha.create_challenge(
            ALGORITHM,
            self.settings.widget_altcha_cost,
            key_prefix=self.settings.widget_altcha_key_prefix,
            expires_at=int(time.time())
            + self.settings.widget_altcha_challenge_ttl_seconds,
            hmac_secret=self._secret(widget),
        )
        return cast(dict[str, Any], challenge.to_dict())

    async def verify(self, payload: str, widget: Widget) -> None:
        try:
            result = _altcha.verify_solution(payload, self._secret(widget))
        except Exception as exc:  # malformed base64 / JSON / fields
            raise ChallengeInvalidError("Malformed challenge solution.") from exc

        if result.expired:
            raise ChallengeInvalidError(
                "Challenge has expired.", code="challenge_expired"
            )
        if not result.verified:
            raise ChallengeInvalidError("Challenge solution is not valid.")

        try:
            parsed = cast(
                dict[str, Any], _altcha.Payload.from_base64(payload).to_dict()
            )
            parameters = cast(dict[str, Any], parsed["challenge"]["parameters"])
            nonce = str(parameters["nonce"])
            expires_at = int(parameters.get("expiresAt") or 0)
        except Exception as exc:
            raise ChallengeInvalidError("Malformed challenge solution.") from exc

        ttl = max(1, expires_at - int(time.time()))
        try:
            fresh = await self.redis.set(
                f"{_REPLAY_PREFIX}{nonce}", b"1", nx=True, ex=ttl
            )
        except redis.exceptions.RedisError as exc:
            if self.settings.widget_rate_limit_fail_open:
                logger.warning(
                    "ALTCHA replay check skipped: Redis unavailable",
                    extra={"error": str(exc)},
                )
                return
            raise WidgetProtectionUnavailableError() from exc
        if not fresh:
            raise ChallengeInvalidError(
                "Challenge solution was already used.", code="challenge_replayed"
            )
