# MIT License

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from intric.analysis.analysis import AnalysisJobStatus


class AnalysisJob(BaseModel):
    job_id: UUID
    tenant_id: UUID
    status: AnalysisJobStatus
    question: str
    assistant_id: UUID | None = None
    group_chat_id: UUID | None = None
    answer: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
