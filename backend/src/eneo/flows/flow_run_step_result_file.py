from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.files.file_models import FileType

FlowRunStepResultFileSource = Literal["generated_output", "declared_artifact"]
FlowRunStepResultFileAvailability = Literal["available", "content_purged"]


class FlowStepResultFileReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    source: FlowRunStepResultFileSource


class FlowRunStepResultFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_run_id: UUID = Field(description="Run that produced this file.")
    flow_id: UUID = Field(description="Flow that owns the run.")
    tenant_id: UUID = Field(description="Tenant that owns the file.")
    step_result_id: UUID = Field(
        description="Step result row this file belongs to.",
    )
    step_id: UUID = Field(
        description="Published step that produced the file. Use it to match a file to a step "
        "from the run contract or the step list.",
    )
    step_order: int = Field(
        description="Position of the producing step in the flow, starting at 1.",
    )
    attempt_no: int = Field(
        description="Execution attempt that produced the file. Only the current attempt's "
        "files are returned.",
    )
    file_id: UUID = Field(
        description="Identifier to download the file with: "
        "`POST {api_prefix}/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/`, "
        "where the prefix is the one this document's own paths use.",
    )
    ordinal: int = Field(
        description="Stable position of this file within its step, starting at 0.",
    )
    source: FlowRunStepResultFileSource = Field(
        description="`generated_output` means the step rendered or generated the file as its "
        "own output, such as a DOCX or PDF. `declared_artifact` means the step's authored "
        "configuration explicitly declared the file as an artifact of the step.",
    )
    name: str = Field(description="Suggested download filename.")
    checksum: str = Field(
        description="Content checksum of the stored bytes, prefixed with its algorithm.",
    )
    size: int = Field(description="Size of the stored bytes in bytes.")
    mimetype: str | None = Field(
        description="Media type of the stored bytes, when one was recorded.",
    )
    file_type: FileType = Field(
        description="Coarse content bucket used by the platform file layer. Branch on "
        "`mimetype` when you need the exact format.",
    )
    availability: FlowRunStepResultFileAvailability = Field(
        description="`available` means the bytes can still be downloaded. `content_purged` "
        "means retention removed the bytes and only this metadata row remains; requesting a "
        "signed URL for it returns `410` with code "
        "`flow_run_artifact_content_unavailable`.",
    )

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
