from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID


class CrawlCircuitResetPreviousState(StrEnum):
    """Captures the circuit-breaker state observed before an explicit operator reset.

    Why: Audit trail must distinguish operator intent (clearing real failure state
    versus a no-op idempotent reset) without leaking raw counter values into the
    enum vocabulary.
    """

    HEALTHY = "HEALTHY"
    BACKED_OFF = "BACKED_OFF"
    AUTO_DISABLED = "AUTO_DISABLED"


@dataclass(frozen=True, slots=True)
class CrawlCircuitResetWebsite:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CrawlCircuitResetSucceeded:
    website: CrawlCircuitResetWebsite
    previous_state: CrawlCircuitResetPreviousState
    previous_consecutive_failures: int
    previous_next_retry_at: datetime | None


@dataclass(frozen=True, slots=True)
class CrawlCircuitResetNotFound:
    website_id: UUID


CrawlCircuitResetResult: TypeAlias = (
    CrawlCircuitResetSucceeded | CrawlCircuitResetNotFound
)
