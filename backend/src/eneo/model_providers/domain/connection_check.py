from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ConnectionCheckStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"


class ConnectionCheckError(StrEnum):
    """Why a connection check failed: a fixed category, never provider text.

    Upstream bodies and headers can echo the key or internal details, so only
    the category is stored and returned; the UI turns it into a sentence.
    """

    AUTHENTICATION_FAILED = "authentication_failed"
    MISSING_CREDENTIALS = "missing_credentials"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    REJECTED = "rejected"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"

    @classmethod
    def parse(cls, value: str) -> "ConnectionCheckError":
        # A category written by a newer release must not break the provider
        # list after a rollback; it still reads as a failure.
        try:
            return cls(value)
        except ValueError:
            return cls.PROVIDER_ERROR


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ConnectionCheck:
    """The latest result of calling a provider with its stored credentials."""

    status: ConnectionCheckStatus
    checked_at: datetime = field(default_factory=_now)
    error: ConnectionCheckError | None = None

    @classmethod
    def ok(cls) -> "ConnectionCheck":
        return cls(status=ConnectionCheckStatus.OK)

    @classmethod
    def failed(cls, error: ConnectionCheckError) -> "ConnectionCheck":
        return cls(status=ConnectionCheckStatus.FAILED, error=error)
