from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eneo.files.file_models import FileType

FlowRunStepResultFileSource = Literal["generated_output", "declared_artifact"]
FlowRunStepResultFileAvailability = Literal["available", "content_purged"]


class FlowStepResultFileReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    source: FlowRunStepResultFileSource


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


def build_step_result_file_references(
    *,
    generated_file_ids: Sequence[UUID],
    artifacts: Sequence[Mapping[str, object]] | None,
) -> list[FlowStepResultFileReference]:
    sources_by_file: dict[UUID, FlowRunStepResultFileSource] = {
        file_id: "generated_output" for file_id in generated_file_ids
    }
    for artifact in artifacts or []:
        raw_file_id = artifact.get("file_id")
        if raw_file_id is None:
            raise ValueError("Step artifact is missing file_id.")
        try:
            file_id = UUID(str(raw_file_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("Step artifact file_id must be a UUID.") from exc
        sources_by_file[file_id] = "declared_artifact"
    return [
        FlowStepResultFileReference(file_id=file_id, source=source)
        for file_id, source in sorted(
            sources_by_file.items(), key=lambda item: str(item[0])
        )
    ]
