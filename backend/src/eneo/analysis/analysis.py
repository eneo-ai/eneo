from datetime import date as LocalDate
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import AliasPath, BaseModel, Field

from eneo.analysis.insight_scope import (
    FindingCaseKind,
    FindingKind,
    InsightTargetKind,
    KnowledgeSourceKind,
    MissReason,
)
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
    negative_with_comment: int = Field(
        description="Answers rated bad (-1) whose rating carries a comment."
    )


class ConversationRatingCounts(BaseModel):
    """Ratings of whole conversations (widget votes land here), counted once
    per conversation of the period."""

    positive: int = Field(description="Conversations rated good (1).")
    negative: int = Field(description="Conversations rated bad (-1).")
    with_comment: int = Field(
        description="Rated conversations whose rating carries a comment."
    )
    negative_with_comment: int = Field(
        description="Conversations rated bad (-1) whose rating carries a comment."
    )


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
    """An assistant or group chat outside personal spaces."""

    id: UUID
    kind: InsightTargetKind
    name: str
    space_id: UUID
    space_name: str
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


class InsightTargetTotals(BaseModel):
    """Everything the organisation used in the period: every listed target
    that matches the filters, not only the page, plus the personal-space
    usage (``personal``), which no filter narrows."""

    conversations: SourceCounts = Field(
        description="Conversations with at least one question in the period."
    )
    questions: int
    previous: Optional[InsightTargetUsage] = Field(
        description="The same in the previous period of equal length, when compare was asked for."
    )


class InsightPersonalUsage(BaseModel):
    """The assistants and group chats in personal spaces, together: one
    figure, never per person or per assistant, and no ratings."""

    assistants: int = Field(
        description=(
            "Assistants and group chats in personal spaces, used or not; hidden "
            "assistants are left out."
        )
    )
    conversations: SourceCounts = Field(
        description="Conversations with at least one question in the period."
    )
    questions: int
    previous: Optional[InsightTargetUsage] = Field(
        description="The same in the previous period of equal length, when compare was asked for."
    )


class InsightTargetCounts(BaseModel):
    """The targets outside personal spaces whose name matches q, whatever
    activity says."""

    all: int = Field(description="Every one of them.")
    unused: int = Field(
        description="Those without a conversation with a question in the period."
    )


class InsightTargetUsers(BaseModel):
    """Distinct signed-in users with a question in the period on any target
    people see, listed or in a personal space, whatever q and activity say.
    API keys and widget visitors are not users; hidden sessions and hidden
    assistants' conversations are left out, as for the usage."""

    current: int = Field(description="In the period.")
    previous: Optional[int] = Field(
        description="In the previous period of equal length, when compare was asked for."
    )


class InsightTargetPage(BaseModel):
    items: list[InsightTarget] = Field(
        description="The page of targets outside personal spaces."
    )
    total_count: int = Field(
        description="Targets outside personal spaces that match the filters."
    )
    limit: int
    offset: int
    totals: InsightTargetTotals
    personal: Optional[InsightPersonalUsage] = Field(
        description=(
            "Every personal-space target together, the same on every page and "
            "whatever the filters; null when the tenant has none."
        )
    )
    counts: InsightTargetCounts
    users: InsightTargetUsers


_PERIOD_START = "Start of the period, inclusive."
_PERIOD_END = "End of the period, exclusive."
_RATING_DESCRIPTION = "The answer's rating (1 good, -1 bad); null when unrated."


class InsightKnowledgeSource(BaseModel):
    kind: KnowledgeSourceKind
    id: UUID
    name: str = Field(
        description="The source's name; a website without a name shows its address."
    )
    attached: bool = Field(
        description=(
            "Attached to the assistant (for a group chat: to one of its member "
            "assistants) now."
        )
    )
    answers: int = Field(
        description="Answers of the period that cited at least one passage from it."
    )


class InsightKnowledgeUse(BaseModel):
    """Which knowledge the period's answers cited. Counts only."""

    timezone: str
    source: Optional[SessionSource] = Field(
        description="The source the figures were limited to; null for all sources."
    )
    start: datetime = Field(description=_PERIOD_START)
    end: datetime = Field(description=_PERIOD_END)
    answers: int = Field(description="Answers (questions) in the period.")
    citing_answers: int = Field(
        description=(
            "Answers that cited at least one passage of a source that still "
            "exists: the base for each source's share."
        )
    )
    sources: list[InsightKnowledgeSource] = Field(
        description=(
            "Every source an answer cited, most cited first, including sources "
            "no longer attached."
        )
    )
    unused: list[InsightKnowledgeSource] = Field(
        description="Attached sources no answer of the period cited, by name."
    )


class InsightQuestionGroup(BaseModel):
    """One group of questions with the same text after normalisation
    (whitespace, letter case and trailing ?!. ignored)."""

    question: str = Field(description="One of the group's questions, as asked.")
    occurrences: int
    share: float = Field(
        description="occurrences divided by total_questions, from 0 to 1."
    )
    conversations: int = Field(
        description="Conversations the group's questions are in."
    )
    unanswered: int = Field(
        description=(
            "Indicative: answers whose text says they cannot answer, found by "
            "phrase matching."
        )
    )
    ratings: MessageFeedbackCounts = Field(description="Ratings of the answers.")
    knowledge: Optional[KnowledgeUse] = Field(
        description=(
            "Indicative, as the summary counts it. Null when the target has no "
            "knowledge attached."
        )
    )
    sample_session_id: UUID = Field(description="One conversation with the question.")


class InsightTopQuestions(BaseModel):
    timezone: str
    source: Optional[SessionSource]
    start: datetime = Field(description=_PERIOD_START)
    end: datetime = Field(description=_PERIOD_END)
    include_followups: bool
    total_questions: int = Field(
        description=(
            "Questions the shares are relative to: every question of the period, "
            "or only the opening ones without include_followups."
        )
    )
    groups: list[InsightQuestionGroup] = Field(
        description="The commonest groups, commonest first."
    )


class InsightToolUse(BaseModel):
    """Calls of one capability or of one server's tool in the period."""

    kind: Literal["capability", "tool"] = Field(
        description=(
            "'capability': every call serving purpose, whichever server backed "
            "it. 'tool': the calls of one server's tool."
        )
    )
    purpose: Optional[str] = Field(
        description="The capability, such as 'web_search' or 'image_generation'."
    )
    server_name: Optional[str] = Field(description="The server, for a tool.")
    tool_name: Optional[str] = Field(description="The tool, for a tool.")
    title: Optional[str] = Field(
        description="The tool's stored display title, when it has one."
    )
    calls: int
    failed: int = Field(description="Calls whose result status is failed.")
    denied: int = Field(
        description="Calls not approved, by the person or by the approval timeout."
    )


class InsightToolUsage(BaseModel):
    """Tool calls of the period's answers, most called first. Calls of
    Eneo's own knowledge server (counted by the knowledge figures) and Skill
    activations are left out."""

    timezone: str
    source: Optional[SessionSource]
    start: datetime = Field(description=_PERIOD_START)
    end: datetime = Field(description=_PERIOD_END)
    tools: list[InsightToolUse]


class InsightFindingExample(BaseModel):
    """One question behind a finding. For rephrasing, a conversation and its
    first question in the period; for negative_ratings, the rated question."""

    question: str
    question_id: Optional[UUID] = Field(
        description="Null for a rating of a whole conversation."
    )
    session_id: UUID
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
    comment: Optional[str] = Field(
        description="The rating's comment, for negative_ratings; null otherwise."
    )


class InsightFinding(BaseModel):
    """Something to look at, worded by its signal, with the counts that make
    it a finding. knowledge_missed, unanswered and rephrasing are indicative:
    they come from stored scores, phrase matching and text similarity."""

    kind: FindingKind = Field(
        description=(
            "knowledge_missed: answers that searched the knowledge without a "
            "usable hit (affected of the answers that searched). unanswered: "
            "answers that say they cannot answer (of all answers). rephrasing: "
            "conversations where the person seems to ask again (of all "
            "conversations). knowledge_unused: attached sources no answer cited "
            "(of the attached sources). negative_ratings: bad ratings with a "
            "comment (of all ratings, answers and conversations). "
            "tool_failures: failed calls of one tool (of its calls)."
        )
    )
    affected: int
    base: int = Field(description="What affected is a share of.")
    examples: list[InsightFindingExample] = Field(
        description=(
            "Up to three: the first cases the findings/{kind}/ route lists "
            "for knowledge_missed, unanswered and rephrasing, the newest bad "
            "ratings with a comment for negative_ratings, none for "
            "knowledge_unused and tool_failures."
        )
    )
    sources: Optional[list[InsightKnowledgeSource]] = Field(
        description="knowledge_unused: the sources nobody cited; null otherwise."
    )
    tool: Optional[InsightToolUse] = Field(
        description="tool_failures: the tool that fails; null otherwise."
    )


class InsightFindings(BaseModel):
    timezone: str
    source: Optional[SessionSource] = Field(
        description="The source the findings were limited to; null for all sources."
    )
    start: datetime = Field(description=_PERIOD_START)
    end: datetime = Field(description=_PERIOD_END)
    findings: list[InsightFinding] = Field(
        description="Most affected first; empty when nothing passes the thresholds."
    )


class KnowledgeMissCase(BaseModel):
    kind: Literal["knowledge_missed"]
    question_id: UUID
    question: str
    session_id: UUID
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
    created_at: datetime
    reason: MissReason = Field(
        description=(
            "no_results: the knowledge search reported no results. uncited: the "
            "answer cited no passage. weak_score: its best passage scored under "
            "the fixed floor."
        )
    )
    best_score: Optional[float] = Field(
        description="The best score among the cited passages; null when none."
    )
    rating: Optional[Literal[-1, 1]] = Field(description=_RATING_DESCRIPTION)


class UnansweredCase(BaseModel):
    kind: Literal["unanswered"]
    question_id: UUID
    question: str
    session_id: UUID
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
    created_at: datetime
    phrase: str = Field(description="The phrase in the answer that matched.")
    rating: Optional[Literal[-1, 1]] = Field(description=_RATING_DESCRIPTION)


class RephrasingCase(BaseModel):
    kind: Literal["rephrasing"]
    session_id: UUID
    source: SessionSource = Field(description=_SOURCE_DESCRIPTION)
    started_at: datetime = Field(
        description="When the conversation's first question in the period was asked."
    )
    questions: list[str] = Field(description="The questions in the period, in order.")
    question_ids: list[UUID] = Field(description="The same questions' ids.")
    similar_pairs: int = Field(
        description="Consecutive questions with textually similar wording."
    )


InsightFindingCase = Annotated[
    Union[KnowledgeMissCase, UnansweredCase, RephrasingCase],
    Field(discriminator="kind"),
]


class InsightFindingCasePage(BaseModel):
    kind: FindingCaseKind
    timezone: str
    source: Optional[SessionSource]
    start: datetime = Field(description=_PERIOD_START)
    end: datetime = Field(description=_PERIOD_END)
    items: list[InsightFindingCase]
    total_count: int = Field(description="Cases of the finding in the period.")
    limit: int
    next_cursor: Optional[str] = Field(
        description="Pass back as cursor for the next page; null on the last page."
    )
