from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FlowRunNotFoundError(Exception):
    run_id: UUID
    tenant_id: UUID
    flow_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class FlowRunPersistenceInvariantError(RuntimeError):
    operation: str
    run_id: UUID | None = None
    tenant_id: UUID | None = None
    flow_id: UUID | None = None
