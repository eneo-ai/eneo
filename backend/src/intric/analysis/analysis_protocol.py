# MIT License

from intric.analysis.analysis import (
    AssistantMetadata,
    MetadataStatistics,
    MetadataStatisticsAggregated,
    MetadataCount,
    QuestionMetadata,
    SessionMetadata,
)
from intric.analysis.analysis_repo import (
    AssistantMetadataRow,
    CountBucketRow,
    QuestionMetadataRow,
    SessionMetadataRow,
)
from intric.assistants.assistant import Assistant
from intric.questions.question import Question
from intric.sessions.session import SessionInDB


def to_metadata(
    assistants: list[Assistant],
    sessions: list[SessionInDB],
    questions: list[Question],
):
    assistants_metadata = [
        AssistantMetadata(
            id=assistant.id,
            created_at=assistant.created_at,
        )
        for assistant in assistants
    ]
    sessions_metadata = [
        SessionMetadata(**session.model_dump()) for session in sessions
    ]
    questions_metadata = [
        QuestionMetadata(**question.model_dump()) for question in questions
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
