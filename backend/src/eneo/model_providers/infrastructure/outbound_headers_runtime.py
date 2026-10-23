"""Apply a provider's configured outbound headers to one outbound request.

Header configuration arrives with the provider row, which every interactive
request and every job loads fresh, and the acting user is the request's or the
job's own. Resolution happens once per request, when its LiteLLM kwargs are
built; a streamed response's tool-call rounds reuse those kwargs.

Nothing here logs a header value. Failures are logged with provider id, header
name and user id so an operator can still tell a mapping gap from a fault.
LiteLLM's own debug logging (off by default) prints whole requests, these
headers included; a warning is logged once if it is on when headers are sent.

NOTE: LiteLLM response caching must stay disabled while this feature is in use.
`extra_headers` is not part of LiteLLM's cache key, so a cached response would
answer a second user's request without it ever reaching the endpoint.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NoReturn, cast
from uuid import UUID

from eneo.main.config import get_settings
from eneo.main.exceptions import (
    EncryptionNotConfiguredException,
    ProviderRejectedRequestException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.outbound_header_destinations import (
    destination_problem,
    parse_allow_list,
)
from eneo.model_providers.domain.outbound_headers import (
    OutboundHeader,
    OutboundHeadersBlocked,
    evaluate_headers,
    request_headers,
    supports_outbound_headers,
)

if TYPE_CHECKING:
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

BLOCKED_MESSAGE = (
    "This request could not be sent because the AI provider's header "
    "configuration could not be applied. Contact your administrator."
)

_litellm_debug_warned = False


def _warn_once_if_litellm_debug_logging() -> None:
    global _litellm_debug_warned
    if _litellm_debug_warned or not logging.getLogger("LiteLLM").isEnabledFor(
        logging.DEBUG
    ):
        return
    _litellm_debug_warned = True
    logger.warning(
        "outbound_headers.litellm_debug_logging_enabled",
        extra={
            "detail": (
                "LiteLLM debug logging is on; it logs full provider requests, "
                "including configured outbound header values. Turn it off in "
                "production."
            )
        },
    )


def decrypt_stored_headers(
    stored: Sequence[Mapping[str, Any]] | None, encryption: EncryptionService
) -> tuple[OutboundHeader, ...]:
    """Stored form → plaintext ``OutboundHeader``s."""
    headers: list[OutboundHeader] = []
    for entry in stored or ():
        secret = bool(entry.get("secret"))
        value = cast(str, entry["value"])
        fallback = cast("str | None", entry.get("fallback"))
        if secret:
            value = encryption.decrypt(value)
            fallback = encryption.decrypt(fallback) if fallback else fallback
        headers.append(
            OutboundHeader(
                id=cast(str, entry["id"]),
                name=cast(str, entry["name"]),
                value=value,
                encoding=entry.get("encoding", "percent"),
                secret=secret,
                on_missing=entry.get("on_missing", "omit"),
                fallback=fallback,
            )
        )
    return tuple(headers)


@dataclass(frozen=True)
class ProviderOutboundHeaders:
    provider_id: UUID
    provider_type: str
    headers: tuple[OutboundHeader, ...]
    user: UserInDB | None = field(repr=False)

    @classmethod
    def load(
        cls,
        *,
        provider_id: UUID,
        provider_type: str,
        stored: Sequence[Mapping[str, Any]] | None,
        encryption: EncryptionService | None,
        user: UserInDB | None,
    ) -> ProviderOutboundHeaders | None:
        """None when the provider has no headers configured."""
        if not stored:
            return None
        if encryption is None:
            raise ProviderRejectedRequestException(
                BLOCKED_MESSAGE,
                code="outbound_headers_blocked",
                details={"reason": "encryption_unavailable", "retryable": False},
            )
        try:
            headers = decrypt_stored_headers(stored, encryption)
        except (ValueError, EncryptionNotConfiguredException):
            # A rotated or missing key. Blocked like any other unusable header
            # configuration, not a 500; the exception text is not logged
            # because it can quote the ciphertext.
            logger.warning(
                "outbound_headers.request_blocked",
                extra={
                    "provider_id": str(provider_id),
                    "header": None,
                    "reason": "decryption_failed",
                    "user_id": str(user.id) if user is not None else None,
                },
            )
            raise ProviderRejectedRequestException(
                BLOCKED_MESSAGE,
                code="outbound_headers_blocked",
                details={"reason": "decryption_failed", "retryable": False},
            ) from None
        return cls(
            provider_id=provider_id,
            provider_type=provider_type,
            headers=headers,
            user=user,
        )

    def resolve(self, endpoint: str | None) -> dict[str, str]:
        """The headers to send to ``endpoint``, or ``ProviderRejectedRequestException``.

        ``endpoint`` must be the request's own ``api_base``. The destination is
        re-checked on every request because an ordinary configuration edit can
        move it after the headers were approved.
        """
        if not supports_outbound_headers(self.provider_type):
            self.reject(None, "unsupported_provider_type")
        allowed = parse_allow_list(get_settings().outbound_headers_allowed_destinations)
        problem = destination_problem(endpoint, allowed)
        if problem is not None:
            self.reject(None, f"destination_{problem}")

        outcomes = evaluate_headers(self.headers, self.user)
        for outcome in outcomes:
            if outcome.state == "missing":
                logger.debug(
                    "outbound_headers.unresolved",
                    extra={
                        "provider_id": str(self.provider_id),
                        "header": outcome.name,
                        "tokens": list(outcome.missing_tokens),
                        "policy": outcome.policy,
                        "user_id": self._user_id,
                    },
                )
        try:
            return request_headers(outcomes)
        except OutboundHeadersBlocked as exc:
            self.reject(exc.header_name, exc.reason)

    @property
    def _user_id(self) -> str | None:
        return str(self.user.id) if self.user is not None else None

    def reject(self, header_name: str | None, reason: str) -> NoReturn:
        # WARNING, not DEBUG: a blocked request is user-visible and someone
        # will be asked why. Never includes the value — for an invalid value it
        # is precisely the one not to log.
        logger.warning(
            "outbound_headers.request_blocked",
            extra={
                "provider_id": str(self.provider_id),
                "header": header_name,
                "reason": reason,
                "user_id": self._user_id,
            },
        )
        details: dict[str, object] = {"reason": reason, "retryable": False}
        if header_name is not None:
            details["header"] = header_name
        raise ProviderRejectedRequestException(
            BLOCKED_MESSAGE, code="outbound_headers_blocked", details=details
        )


def apply_outbound_headers(
    kwargs: dict[str, Any], outbound_headers: ProviderOutboundHeaders | None
) -> None:
    """Add the resolved headers to LiteLLM ``kwargs`` in place.

    No configuration adds no kwarg at all, so such requests are byte-identical
    to before the feature. A collision with a header already in the outgoing
    mapping raises rather than letting either side silently win.
    """
    if outbound_headers is None:
        return
    headers = outbound_headers.resolve(cast("str | None", kwargs.get("api_base")))
    if not headers:
        return
    existing = cast(dict[str, str], kwargs.get("extra_headers") or {})
    existing_names = {name.casefold() for name in existing}
    for name in headers:
        if name.casefold() in existing_names:
            outbound_headers.reject(name, "adapter_header_collision")
    _warn_once_if_litellm_debug_logging()
    kwargs["extra_headers"] = {**existing, **headers}


def mask_outbound_headers(params: dict[str, Any]) -> dict[str, Any]:
    """For logging: keep header names, drop every value."""
    headers = params.get("extra_headers")
    if isinstance(headers, dict):
        params = {
            **params,
            "extra_headers": dict.fromkeys(cast(dict[str, Any], headers), "***"),
        }
    return params
