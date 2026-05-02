from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from intric.files.file_models import FileType

FlowRunStepResultFileSource = Literal["generated_output", "declared_artifact"]
FlowRunStepResultFileAvailability = Literal["available", "content_purged"]


class FlowRunStepResultFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_result_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    file_id: UUID
    ordinal: int
    source: FlowRunStepResultFileSource
    name: str
    checksum: str
    size: int
    mimetype: str | None
    file_type: FileType
    availability: FlowRunStepResultFileAvailability

    @property
    def content_available(self) -> bool:
        return self.availability == "available"
