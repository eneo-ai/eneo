# MIT License

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sse_starlette import EventSourceResponse

from intric.ai_models.completion_models.completion_model import Completion
from intric.analysis import analysis_protocol
from intric.analysis.analysis import (
    AnalysisAnswer,
    AnalysisJobCreateResponse,
    AnalysisJobStatus,
    AnalysisJobStatusResponse,
    AnalysisProcessingMode,
    AskAnalysis,
    AssistantInsightQuestion,
    AssistantActivityStats,
    ConversationInsightRequest,
    ConversationInsightResponse,
    Counts,
    MetadataStatistics,
    MetadataStatisticsAggregated,
)
from intric.analysis.analysis_job_manager import AnalysisJobManager
from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Task
from intric.jobs.task_models import AnalyzeConversationInsightsTask
from intric.sessions.session import SessionPublic, SessionMetadataPublic
from intric.sessions.session_protocol import (
    to_session_metadata_paginated_response,
    to_session_public,
)
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException, NotFoundException
from intric.main.logging import get_logger
from intric.main.models import PaginatedResponse, CursorPaginatedResponse
from intric.questions import question_protocol
from intric.questions.question import Message
from intric.server import protocol
from intric.server.dependencies.container import get_container

logger = get_logger(__name__)

router = APIRouter()
DEFAULT_INSIGHTS_DAYS = 30
DEFAULT_SESSIONS_PAGE_LIMIT = 50
DEFAULT_QUESTIONS_PAGE_LIMIT = 100


def _normalize_datetime_range(
    *,
    from_date: datetime | None,
    to_date: datetime | None,
    days_since: int,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if from_date is None:
        from_date = now - timedelta(days=days_since)
    if to_date is None:
        to_date = now
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)
    if from_date > to_date:
        raise BadRequestException("from_date must be before to_date")
    return from_date, to_date


def _default_analytics_range(
    *,
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    resolved_start = start_date if start_date is not None else now - timedelta(days=30)
    resolved_end = end_date if end_date is not None else now + timedelta(hours=1, minutes=1)
    if resolved_start.tzinfo is None:
        resolved_start = resolved_start.replace(tzinfo=timezone.utc)
    if resolved_end.tzinfo is None:
        resolved_end = resolved_end.replace(tzinfo=timezone.utc)
    return resolved_start, resolved_end


@router.get("/counts/", response_model=Counts)
async def get_counts(container: Container = Depends(get_container(with_user=True))):
    """Total counts."""
    service = container.analysis_service()
    return await service.get_tenant_counts()


@router.get("/metadata-statistics/")
async def get_metadata(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    container: Container = Depends(get_container(with_user=True)),
) -> MetadataStatistics:
    """Data for analytics.

    Note on datetime parameters:
    - If no time is provided in the datetime, time components default to 00:00:00
    """
    start_date, end_date = _default_analytics_range(
        start_date=start_date, end_date=end_date
    )

    service = container.analysis_service()
    assistants, sessions, questions = await service.get_metadata_statistics(
        start_date, end_date
    )

    return analysis_protocol.to_metadata_from_rows(
        assistants=assistants, sessions=sessions, questions=questions
    )


@router.get("/assistant-activity/", response_model=AssistantActivityStats)
async def get_assistant_activity(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    container: Container = Depends(get_container(with_user=True)),
):
    """Get assistant activity statistics for the tenant.

    Returns:
    - active_assistant_count: Number of assistants with sessions in the period
    - total_trackable_assistants: Number of published assistants with insights enabled
    - active_assistant_pct: Percentage of trackable assistants that are active
    - active_user_count: Number of unique users with sessions (excluding service sessions
      and deleted users)

    Note on datetime parameters:
    - If no time is provided in the datetime, time components default to 00:00:00
    """
    start_date, end_date = _default_analytics_range(
        start_date=start_date, end_date=end_date
    )

    service = container.analysis_service()
    return await service.get_assistant_activity_stats(start_date, end_date)


@router.get(
    "/metadata-statistics/aggregated/", response_model=MetadataStatisticsAggregated
)
async def get_metadata_aggregated(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    container: Container = Depends(get_container(with_user=True)),
):
    """Aggregated data for analytics (hourly buckets)."""
    start_date, end_date = _default_analytics_range(
        start_date=start_date, end_date=end_date
    )

    service = container.analysis_service()
    assistants, sessions, questions = await service.get_metadata_statistics_aggregated(
        start_date, end_date
    )

    return analysis_protocol.to_metadata_aggregated(
        assistants=assistants, sessions=sessions, questions=questions
    )


@router.get("/assistants/{assistant_id}/", response_model=PaginatedResponse[Message])
async def get_most_recent_questions(
    assistant_id: UUID,
    days_since: int = Query(ge=0, le=90, default=30),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all the questions asked to an assistant in the last `days_since` days.

    `days_since`: How long back in time to get the questions.

    `from_date`: Start date for filtering questions.
        If no time is provided, time components default to 00:00:00.

    `to_date`: End date for filtering questions.
        If no time is provided, time components default to 00:00:00.

    `include_followups`: If not selected, only the first question of a session is returned.
        Order is by date ascending, but if followups are included they are grouped together
        with their original question.
    """
    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )

    service = container.analysis_service()
    questions = await service.get_questions_since(
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
        include_followups=include_followups,
    )

    return protocol.to_paginated_response(
        [question_protocol.to_question_public(question) for question in questions]
    )


@router.get(
    "/assistants/{assistant_id}/questions/",
    response_model=CursorPaginatedResponse[AssistantInsightQuestion],
)
async def get_most_recent_questions_paginated(
    assistant_id: UUID,
    days_since: int = Query(ge=0, le=90, default=30),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    limit: int = Query(DEFAULT_QUESTIONS_PAGE_LIMIT, ge=1, le=200),
    cursor: str | None = None,
    q: str | None = None,
    container: Container = Depends(get_container(with_user=True)),
):
    """Get paginated question history for an assistant.

    Optimized for admin insights history view and large datasets.
    """
    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )
    if q is not None:
        q = q.strip() or None

    service = container.analysis_service()
    items, total_count, next_cursor = (
        await service.get_assistant_question_history_page(
            assistant_id=assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followups,
            limit=limit,
            query=q,
            cursor=cursor,
        )
    )

    return CursorPaginatedResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        next_cursor=next_cursor,
        previous_cursor=cursor,
    )


@router.post("/assistants/{assistant_id}/")
async def ask_question_about_questions(
    assistant_id: UUID,
    ask_analysis: AskAnalysis,
    days_since: int = Query(ge=0, le=90, default=30),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    """Ask a question with the questions asked to an assistant in the last
      `days_since` days as the context.

    `days_since`: How long back in time to get the questions.

    `from_date`: Start date for filtering questions.
        If no time is provided, time components default to 00:00:00.

    `to_date`: End date for filtering questions.
        If no time is provided, time components default to 00:00:00.

    `include_followups`: If not selected, only the first question of a session is returned.
        Order is by date ascending, but if followups are included they are grouped together
        with their original question.
    """
    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )

    service = container.analysis_service()
    ai_response = await service.ask_question_on_questions(
        question=ask_analysis.question,
        stream=ask_analysis.stream,
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
        include_followup=include_followups,
    )

    if ask_analysis.stream:

        async def event_stream():
            async for chunk in ai_response.completion:
                yield AnalysisAnswer(answer=chunk.text).model_dump_json()

        return EventSourceResponse(event_stream())

    completion = ai_response.completion
    if not isinstance(completion, Completion):
        raise ValueError("Expected Completion object for non-streaming response")
    return AnalysisAnswer(answer=completion.text or "")


@router.post("/conversation-insights/")
async def ask_unified_questions_about_questions(
    ask_analysis: AskAnalysis,
    days_since: int = Query(ge=0, le=90, default=DEFAULT_INSIGHTS_DAYS),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    processing_mode: AnalysisProcessingMode = Query(AnalysisProcessingMode.SYNC),
    container: Container = Depends(get_container(with_user=True)),
):
    """Ask a question about the questions asked to an assistant or group chat.

    This unified endpoint works with both assistants and group chats.
    Either assistant_id or group_chat_id must be provided, but not both.

    Args:
        ask_analysis: Contains the question and streaming preference
        days_since: How long back in time to get the questions
        from_date: Start date to filter questions (overrides days_since).
            If no time is provided, time components default to 00:00:00.
        to_date: End date to filter questions (overrides days_since).
            If no time is provided, time components default to 00:00:00.
        include_followups: If False, only returns first question of each session
        assistant_id: UUID of assistant to analyze questions for
        group_chat_id: UUID of group chat to analyze questions for

    Returns:
        AnalysisAnswer containing the AI response
    """
    if assistant_id is None and group_chat_id is None:
        raise BadRequestException(
            "Either assistant_id or group_chat_id must be provided"
        )

    if assistant_id is not None and group_chat_id is not None:
        raise BadRequestException(
            "Only one of assistant_id or group_chat_id should be provided"
        )

    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )

    service = container.analysis_service()
    if ask_analysis.stream and processing_mode == AnalysisProcessingMode.AUTO:
        # Streaming requires immediate sync execution.
        processing_mode = AnalysisProcessingMode.SYNC

    should_queue_job = await service.should_queue_unified_analysis_job(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        from_date=from_date,
        to_date=to_date,
        mode=processing_mode,
    )

    if should_queue_job:
        tenant_id = container.user().tenant_id
        user_id = container.user().id
        new_job_id = uuid4()
        manager = AnalysisJobManager(container.redis_client())
        await manager.create_job(
            job_id=new_job_id,
            tenant_id=tenant_id,
            question=ask_analysis.question,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
        )
        await job_manager.enqueue(
            task=Task.ANALYZE_CONVERSATION_INSIGHTS,
            job_id=new_job_id,
            params=AnalyzeConversationInsightsTask(
                user_id=user_id,
                question=ask_analysis.question,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                include_followups=include_followups,
                assistant_id=assistant_id,
                group_chat_id=group_chat_id,
            ),
        )
        return AnalysisJobCreateResponse(
            job_id=new_job_id,
            status=AnalysisJobStatus.QUEUED,
            is_async=True,
            answer=None,
        )

    ai_response = await service.unified_ask_question_on_questions(
        question=ask_analysis.question,
        stream=ask_analysis.stream,
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        from_date=from_date,
        to_date=to_date,
        include_followup=include_followups,
    )

    if ask_analysis.stream:

        async def event_stream():
            async for chunk in ai_response.completion:
                yield AnalysisAnswer(answer=chunk.text).model_dump_json()

        return EventSourceResponse(event_stream())

    completion = ai_response.completion
    if not isinstance(completion, Completion):
        raise ValueError("Expected Completion object for non-streaming response")
    answer_text = completion.text or ""

    if processing_mode == AnalysisProcessingMode.AUTO:
        return AnalysisJobCreateResponse(
            job_id=None,
            status=AnalysisJobStatus.COMPLETED,
            is_async=False,
            answer=answer_text,
        )

    return AnalysisAnswer(answer=answer_text)


@router.get(
    "/conversation-insights/",
    response_model=ConversationInsightResponse,
    responses={
        403: {
            "description": "Forbidden - Either user is not ADMIN/EDITOR or insights are not enabled"
        }
    },
)
async def get_conversation_insights(
    request: ConversationInsightRequest = Depends(),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get statistics about conversations for either an assistant or a group chat.

    Either assistant_id or group_chat_id must be provided, but not both.
    Start time and end time are optional filters. If no time is provided in the datetime parameters,
    time components default to 00:00:00.
    """
    start_time = request.start_time
    end_time = request.end_time
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time is not None and end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    service = container.analysis_service()
    return await service.get_conversation_stats(
        assistant_id=request.assistant_id,
        group_chat_id=request.group_chat_id,
        start_time=start_time,
        end_time=end_time,
    )


@router.get(
    "/conversation-insights/jobs/{job_id}/",
    response_model=AnalysisJobStatusResponse,
)
async def get_conversation_insight_job(
    job_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    manager = AnalysisJobManager(container.redis_client())
    tenant_id = container.user().tenant_id
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise NotFoundException("Insights analysis job not found")

    return AnalysisJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        answer=job.answer,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get(
    "/conversation-insights/sessions/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    responses={
        403: {
            "description": "Forbidden - Either user is not ADMIN/EDITOR or insights are not enabled"
        }
    },
)
async def get_conversation_insight_sessions(
    assistant_id: Optional[UUID] = None,
    group_chat_id: Optional[UUID] = None,
    limit: Optional[int] = Query(DEFAULT_SESSIONS_PAGE_LIMIT, ge=1, le=100),
    cursor: Optional[datetime] = None,
    previous: bool = False,
    name_filter: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get all sessions for an assistant or group chat across all
    users in the tenant (with insight access).

    This endpoint requires the user to be OWNER or EDITOR,
    and the assistant/group chat must have insight_enabled set to true.

    Args:
        assistant_id: UUID of the assistant (optional)
        group_chat_id: UUID of the group chat (optional)
        limit: Maximum number of sessions to return
        cursor: Datetime to start fetching from. If no time is provided, time defaults to 00:00:00.
        previous: Whether to fetch sessions before or after the cursor
        name_filter: Filter sessions by name
        start_date: Start date to filter sessions (optional).
            If no time is provided, time components default to 00:00:00.
        end_date: End date to filter sessions (optional).
            If no time is provided, time components default to 00:00:00.

    Returns:
        Paginated list of sessions
    """
    if not assistant_id and not group_chat_id:
        raise BadRequestException(
            "Either assistant_id or group_chat_id must be provided"
        )

    if assistant_id and group_chat_id:
        raise BadRequestException(
            "Only one of assistant_id or group_chat_id should be provided"
        )

    if cursor is not None and cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=timezone.utc)
    if start_date is not None and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date is not None and end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    if name_filter is not None:
        name_filter = name_filter.strip() or None

    service = container.analysis_service()

    if assistant_id:
        sessions, total = await service.get_assistant_insight_sessions(
            assistant_id=assistant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        sessions, total = await service.get_group_chat_insight_sessions(
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
        )

    return to_session_metadata_paginated_response(
        sessions=sessions,
        total_count=total,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )


@router.get(
    "/conversation-insights/sessions/{session_id}/",
    response_model=SessionPublic,
    responses={
        403: {
            "description": "Forbidden - Either user is not ADMIN/EDITOR or insights are not enabled"
        }
    },
)
async def get_conversation_insight_session(
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get a specific session with insight access.

    This endpoint requires the user to be OWNER or EDITOR, and the assistant/group chat
    must have insight_enabled set to true.

    Args:
        session_id: UUID of the session
        assistant_id: UUID of the assistant (optional)
        group_chat_id: UUID of the group chat (optional)

    Returns:
        Session data
    """

    service = container.analysis_service()
    session = await service.get_insight_session(session_id=session_id)
    return to_session_public(session=session)
