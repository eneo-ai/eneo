from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FlowRunRuntimeUploadBindingRaceError(Exception):
    step_id: UUID
    file_ids: tuple[UUID, ...]
