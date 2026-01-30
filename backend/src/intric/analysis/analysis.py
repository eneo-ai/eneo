# MIT License

from datetime import datetime
from uuid import UUID

from pydantic import AliasPath, BaseModel, Field
from typing import Optional


class AssistantMetadata(BaseModel):
    id: UUID
    created_at: datetime


class SessionMetadata(AssistantMetadata):
    assistant_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasPath("assistant", "id"),
    )
    group_chat_id: Optional[UUID] = None


class QuestionMetadata(AssistantMetadata):
    assistant_id: Optional[UUID] = None
    session_id: UUID


class MetadataStatistics(BaseModel):
    assistants: list[AssistantMetadata]
    sessions: list[SessionMetadata]
    questions: list[QuestionMetadata]


class MetadataCount(BaseModel):
    created_at: datetime
    count: int


class MetadataStatisticsAggregated(BaseModel):
    assistants: list[MetadataCount]
    sessions: list[MetadataCount]
    questions: list[MetadataCount]


class Counts(BaseModel):
    assistants: int
    sessions: int
    questions: int


class AskAnalysis(BaseModel):
    question: str
    completion_model_id: UUID | None = None
    stream: bool = False


class AnalysisAnswer(BaseModel):
    answer: str


class ConversationInsightRequest(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None


class ConversationInsightResponse(BaseModel):
    total_conversations: int
    total_questions: int


class AssistantActivityStats(BaseModel):
    """Statistics about assistant activity within a period."""

    active_assistant_count: int
    total_trackable_assistants: int
    active_assistant_pct: float
    active_user_count: int
