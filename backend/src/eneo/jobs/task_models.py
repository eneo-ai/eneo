from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from eneo.jobs.job_models import Task
from eneo.object_content.content import StorageKind


class TaskParams(BaseModel):
    user_id: UUID


class ResourceTaskParams(TaskParams):
    id: UUID


class KnowledgeTask(TaskParams):
    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None


class InfoBlobTask(TaskParams):
    group_id: UUID
    space_id: UUID


class KnowledgeOriginalAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_revision: int = Field(ge=1)
    storage_target: StorageKind
    maximum_bytes: int = Field(ge=1)


class UploadTask(InfoBlobTask):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    mimetype: str
    original_storage: KnowledgeOriginalAdmission


class UpdateUsageStatsTaskParams(TaskParams):
    """Parameters for updating completion model usage statistics."""

    tenant_id: UUID
    model_id: Optional[UUID] = None
    full_recalc: bool = False


class UploadInfoBlob(UploadTask):
    pass


class Transcription(UploadTask):
    pass


class UploadInfoBlobDispatchEnvelope(BaseModel):
    version: Literal[2] = 2
    task: Literal[Task.UPLOAD_FILE] = Task.UPLOAD_FILE
    params: UploadInfoBlob


class TranscriptionDispatchEnvelope(BaseModel):
    version: Literal[2] = 2
    task: Literal[Task.TRANSCRIPTION] = Task.TRANSCRIPTION
    params: Transcription


DispatchEnvelope = UploadInfoBlobDispatchEnvelope | TranscriptionDispatchEnvelope
_DISPATCH_ENVELOPE_ADAPTER: TypeAdapter[DispatchEnvelope] = TypeAdapter(
    DispatchEnvelope
)


def build_dispatch_envelope(
    task: Task, params: UploadInfoBlob | Transcription
) -> DispatchEnvelope:
    if task == Task.UPLOAD_FILE and isinstance(params, UploadInfoBlob):
        return UploadInfoBlobDispatchEnvelope(params=params)
    if task == Task.TRANSCRIPTION and isinstance(params, Transcription):
        return TranscriptionDispatchEnvelope(params=params)
    raise ValueError(f"Unsupported durable dispatch task: {task.value}")


def validate_dispatch_envelope(value: object) -> DispatchEnvelope:
    return _DISPATCH_ENVELOPE_ADAPTER.validate_python(value)


class AnalyzeConversationInsightsTask(TaskParams):
    question: str
    from_date: str
    to_date: str
    include_followups: bool = False
    assistant_id: UUID | None = None
    group_chat_id: UUID | None = None
