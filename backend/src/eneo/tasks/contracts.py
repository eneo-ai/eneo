from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol


class TaskCapacityClass(StrEnum):
    EXECUTION = "execution"
    MAINTENANCE = "maintenance"


class TaskEnqueueStatus(StrEnum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True)
class TaskEnqueueRequest:
    task_name: str
    capacity_class: TaskCapacityClass
    idempotency_key: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TaskEnqueueResult:
    status: TaskEnqueueStatus
    task_id: str | None = None


class TaskEnqueuer(Protocol):
    async def enqueue(self, request: TaskEnqueueRequest) -> TaskEnqueueResult: ...


@dataclass(frozen=True, slots=True)
class TaskWorkerReadiness:
    execution_ready: bool
    maintenance_ready: bool
