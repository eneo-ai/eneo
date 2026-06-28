# MIT License

from eneo.analysis.analysis import (
    AssistantMetadata,
    MetadataCount,
    MetadataStatistics,
    MetadataStatisticsAggregated,
    QuestionMetadata,
    SessionMetadata,
)
from eneo.analysis.analysis_repo import (
    AssistantMetadataRow,
    CountBucketRow,
    QuestionMetadataRow,
    SessionMetadataRow,
)
from eneo.assistants.assistant import Assistant
from eneo.questions.question import Question
from eneo.sessions.session import SessionInDB


def to_metadata(
    assistants: list[Assistant],
    sessions: list[SessionInDB],
    questions: list[Question],
) -> MetadataStatistics:
    assistants_metadata = [
        AssistantMetadata(
            id=assistant.id,  # type: ignore[arg-type]  # Entity.id is UUID|None; callers guarantee non-None for persisted assistants
            created_at=assistant.created_at,  # type: ignore[arg-type]  # InDB.created_at is Optional[datetime]; persisted objects always have created_at set
        )
        for assistant in assistants
    ]
    sessions_metadata = [
        SessionMetadata(
            id=session.id,  # type: ignore[arg-type]  # InDB.id is Optional[UUID]; persisted sessions always have id set
            created_at=session.created_at,  # type: ignore[arg-type]  # InDB.created_at is Optional[datetime]; persisted sessions always have created_at
            assistant_id=session.assistant.id if session.assistant else None,  # type: ignore[union-attr]  # assistant.id is UUID|None; if present it's set
            group_chat_id=session.group_chat_id,
        )
        for session in sessions
    ]
    questions_metadata = [
        QuestionMetadata(
            id=question.id,  # type: ignore[arg-type]  # same Optional[UUID] pattern
            created_at=question.created_at,  # type: ignore[arg-type]  # same Optional[datetime] pattern
            assistant_id=question.assistant_id,
            session_id=question.session_id,  # type: ignore[arg-type]  # session_id is Optional[UUID]; persisted questions always have it
        )
        for question in questions
    ]

    return MetadataStatistics(
        assistants=assistants_metadata,
        sessions=sessions_metadata,
        questions=questions_metadata,
    )


def to_metadata_from_rows(
    assistants: list[AssistantMetadataRow],
    sessions: list[SessionMetadataRow],
    questions: list[QuestionMetadataRow],
) -> MetadataStatistics:
    """Convert lightweight metadata rows to MetadataStatistics response.

    This is the optimized version that works with column-projection queries
    instead of full ORM objects.
    """
    assistants_metadata = [
        AssistantMetadata(id=row.id, created_at=row.created_at) for row in assistants
    ]
    sessions_metadata = [
        SessionMetadata(
            id=row.id,
            created_at=row.created_at,
            assistant_id=row.assistant_id,
            group_chat_id=row.group_chat_id,
        )
        for row in sessions
    ]
    questions_metadata = [
        QuestionMetadata(
            id=row.id,
            created_at=row.created_at,
            assistant_id=row.assistant_id,
            session_id=row.session_id,
        )
        for row in questions
    ]

    return MetadataStatistics(
        assistants=assistants_metadata,
        sessions=sessions_metadata,
        questions=questions_metadata,
    )


def to_metadata_aggregated(
    assistants: list[CountBucketRow],
    sessions: list[CountBucketRow],
    questions: list[CountBucketRow],
) -> MetadataStatisticsAggregated:
    assistants_metadata = [
        MetadataCount(created_at=row.created_at, count=row.total) for row in assistants
    ]
    sessions_metadata = [
        MetadataCount(created_at=row.created_at, count=row.total) for row in sessions
    ]
    questions_metadata = [
        MetadataCount(created_at=row.created_at, count=row.total) for row in questions
    ]

    return MetadataStatisticsAggregated(
        assistants=assistants_metadata,
        sessions=sessions_metadata,
        questions=questions_metadata,
    )
