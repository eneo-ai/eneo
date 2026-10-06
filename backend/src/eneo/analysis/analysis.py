# MIT License

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import AliasPath, BaseModel, Field

from eneo.questions.question import MessageFeedback


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


class AnalysisProcessingMode(str, Enum):
    SYNC = "sync"
    AUTO = "auto"


class ConversationInsightRequest(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None


class MessageFeedbackCounts(BaseModel):
    """How many answers their conversation owners rated good and bad."""

    positive: int = Field(description="Answers rated good (1).")
    negative: int = Field(description="Answers rated bad (-1).")


class ConversationInsightResponse(BaseModel):
    total_conversations: int
    total_questions: int
    feedback: MessageFeedbackCounts = Field(
        description=(
            "Ratings on the answers in these conversations. Conversation-level "
            "feedback is not included."
        )
    )


class AssistantInsightQuestion(BaseModel):
    id: UUID
    question: str
    created_at: datetime
    session_id: UUID
    feedback: Optional[MessageFeedback] = Field(
        default=None,
        description="The conversation owner's rating of the answer; null when unrated.",
    )


class AnalysisJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisJobCreateResponse(BaseModel):
    job_id: UUID | None = None
    status: AnalysisJobStatus
    is_async: bool
    answer: str | None = None


class AnalysisJobStatusResponse(BaseModel):
    job_id: UUID
    status: AnalysisJobStatus
    answer: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AssistantActivityStats(BaseModel):
    """Statistics about assistant activity within a period."""

    active_assistant_count: int
    total_trackable_assistants: int
    active_assistant_pct: float
    active_user_count: int
