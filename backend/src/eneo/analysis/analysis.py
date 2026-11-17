from datetime import date as LocalDate
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import AliasPath, BaseModel, Field

from eneo.analysis.insight_scope import InsightTargetKind
from eneo.questions.question import MessageFeedback
from eneo.sessions.session_source import SessionSource

_SOURCE_DESCRIPTION = (
    "Who the conversation is with: 'user' (a signed-in user), 'api_key' (a "
    "service API key) or 'widget' (a visitor of a website widget)."
)


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
    source: Optional[SessionSource] = Field(
        default=None,
        description="Count only conversations of this source; all sources when omitted.",
    )


class MessageFeedbackCounts(BaseModel):
    """How many answers their conversation owners rated good and bad."""

    positive: int = Field(description="Answers rated good (1).")
    negative: int = Field(description="Answers rated bad (-1).")


class ConversationInsightResponse(BaseModel):
    total_conversations: int = Field(
        description=(
            "Conversations started in the period, from every source (users, "
            "service API keys and widget visitors) unless a source is asked for."
        )
    )
    total_questions: int = Field(
        description="Questions in the conversations counted in total_conversations."
    )
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
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
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


class SourceCounts(BaseModel):
    """A count in total and per source."""

    total: int = Field(description="Every source together.")
    user: int = Field(description="Of signed-in users.")
    api_key: int = Field(description="Of service API keys.")
    widget: int = Field(description="Of website widget visitors.")


class KnowledgeUse(BaseModel):
    """Indicative: how answers used the target's knowledge, from what each
    answer stored."""

    searched: int = Field(
        description=(
            "Answers that searched the knowledge: they cited a passage, called "
            "the knowledge search, or were given by an assistant that retrieves "
            "on every turn (judged by its current knowledge settings). In tool "
            "mode an answer that never searched is not counted."
        )
    )
    missed: int = Field(
        description=(
            "Of the searched answers, those without a usable hit: the search "
            "reported no results, nothing was cited, or the best passage scored "
            "under the fixed floor. Absolute signals only."
        )
    )


class AnswerRatingCounts(MessageFeedbackCounts):
    """Ratings of single answers in the period."""

    with_comment: int = Field(description="Answer ratings that carry a comment.")


class ConversationRatingCounts(BaseModel):
    """Ratings of whole conversations (widget votes land here), counted once
    per conversation of the period."""

    positive: int = Field(description="Conversations rated good (1).")
    negative: int = Field(description="Conversations rated bad (-1).")


class InsightPeriodSummary(BaseModel):
    """The figures of one period. Every figure is derived from live rows, so
    periods older than the retention period shrink as rows are removed."""

    start: datetime = Field(description="Start of the period, inclusive.")
    end: datetime = Field(description="End of the period, exclusive.")
    conversations: SourceCounts = Field(
        description="Conversations with at least one question in the period."
    )
    questions: SourceCounts = Field(description="Questions asked in the period.")
    followups: int = Field(
        description="Questions that were not the first of their conversation."
    )
    users: int = Field(
        description="Distinct signed-in users; API keys and widget visitors are not users."
    )
    single_question_conversations: int = Field(
        description=(
            "Conversations of the period that have exactly one question: they "
            "ended after the first answer."
        )
    )
    returning_users: int = Field(
        description=(
            "Signed-in users who asked on more than one local day of the period, "
            "in the requested timezone."
        )
    )
    unanswered: int = Field(
        description=(
            "Indicative: answers whose text says they cannot answer, found by "
            "phrase matching."
        )
    )
    knowledge: Optional[KnowledgeUse] = Field(
        description="Indicative. Null when the target has no knowledge attached."
    )
    answer_ratings: AnswerRatingCounts
    conversation_ratings: ConversationRatingCounts


class InsightSummary(BaseModel):
    timezone: str
    source: Optional[SessionSource] = Field(
        description="The source the figures were limited to; null for all sources."
    )
    period: InsightPeriodSummary
    previous: Optional[InsightPeriodSummary] = Field(
        description=(
            "The same figures for the period of equal length just before, when "
            "compare was asked for. Reliable only inside the retention period."
        )
    )


class InsightActivityDay(BaseModel):
    date: LocalDate = Field(
        description="A local calendar day in the requested timezone."
    )
    conversations: SourceCounts = Field(
        description="Conversations with a question that day."
    )
    questions: SourceCounts


class InsightActivity(BaseModel):
    timezone: str
    source: Optional[SessionSource]
    start: datetime
    end: datetime
    days: list[InsightActivityDay] = Field(
        description="Days with at least one question, oldest first."
    )


class InsightRating(BaseModel):
    """One rating, never who gave it."""

    kind: Literal["answer", "conversation"]
    value: Literal[-1, 1]
    comment: Optional[str]
    question: str = Field(
        description=(
            "The rated answer's question, or a conversation rating's first question."
        )
    )
    question_id: Optional[UUID] = Field(
        description="The rated answer's question; null for a conversation rating."
    )
    session_id: UUID
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
    created_at: datetime = Field(
        description=(
            "When the rating was given, from the stored timestamps. A widget "
            "conversation vote without a comment keeps the time of its last "
            "comment, or of the conversation's start."
        )
    )


class InsightTargetUsage(BaseModel):
    conversations: SourceCounts = Field(
        description="Conversations with at least one question in the period."
    )
    questions: int


class InsightTarget(BaseModel):
    id: UUID
    kind: InsightTargetKind
    name: str
    space_id: UUID
    space_name: str
    personal_space: bool = Field(
        description="The target lives in a user's personal space."
    )
    insight_enabled: bool
    conversations: SourceCounts = Field(
        description="Conversations with at least one question in the period."
    )
    questions: int
    previous: Optional[InsightTargetUsage] = Field(
        description="Usage in the previous period of equal length, when compare was asked for."
    )
    ratings: Optional[MessageFeedbackCounts] = Field(
        description=(
            "Answer ratings in the period; null when insights are off for the "
            "target, which shows usage only."
        )
    )


class InsightTargetPage(BaseModel):
    items: list[InsightTarget]
    total_count: int = Field(description="Targets matching the filters.")
    limit: int
    offset: int
