from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(eq=False)
class FlowRunRuntimeUploadBindingRaceError(Exception):
    step_id: UUID
    file_ids: tuple[UUID, ...]
