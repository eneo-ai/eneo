from typing import Optional
from uuid import UUID

from pydantic import BaseModel


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


class UploadTask(InfoBlobTask):
    filepath: str
    filename: str
    mimetype: str


class UpdateUsageStatsTaskParams(TaskParams):
    """Parameters for updating completion model usage statistics."""
    tenant_id: UUID
    model_id: Optional[UUID] = None
    full_recalc: bool = False


class UploadInfoBlob(UploadTask):
    pass


class Transcription(UploadTask):
    pass
