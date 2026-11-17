from datetime import datetime, timedelta, timezone
from typing import Annotated, AsyncIterator, Literal, Optional, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query

from eneo.ai_models.completion_models.completion_model import Completion, ResponseType
from eneo.analysis import analysis_protocol
from eneo.analysis.analysis import (
    AnalysisAnswer,
    AnalysisJobCreateResponse,
    AnalysisJobStatus,
    AnalysisJobStatusResponse,
    AnalysisProcessingMode,
    AskAnalysis,
    AssistantActivityStats,
    AssistantInsightQuestion,
    ConversationInsightRequest,
    ConversationInsightResponse,
    Counts,
    InsightActivity,
    InsightFindingCasePage,
    InsightFindings,
    InsightKnowledgeUse,
    InsightRating,
    InsightSummary,
    InsightTargetPage,
    InsightToolUsage,
    InsightTopQuestions,
    MessageFeedbackCounts,
    MetadataStatistics,
    MetadataStatisticsAggregated,
)
from eneo.analysis.analysis_job_manager import AnalysisJobManager
from eneo.analysis.insight_figures_service import resolve_window
from eneo.analysis.insight_scope import FindingCaseKind
from eneo.analysis.insights_repo import TargetSort
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import AnalyzeConversationInsightsTask
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    InternalServerException,
    NotFoundException,
)
from eneo.main.logging import get_logger
from eneo.main.models import CursorPaginatedResponse, PaginatedResponse
from eneo.questions import question_protocol
from eneo.questions.question import Message
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.server.protocol.sse import ClosingEventSourceResponse, closing
from eneo.sessions.session import SourcedSessionMetadata, SourcedSessionPublic
from eneo.sessions.session_protocol import (
    to_session_metadata_paginated_response,
    to_sourced_session_public,
)
from eneo.sessions.session_source import SessionSource

_TENANT_ANALYTICS_ACCESS_REASON = "Tenant analytics require the insights permission."
_RESOURCE_INSIGHTS_ACCESS_REASON = (
    "AnalysisService checks insight access to the requested assistant or group chat."
)

logger = get_logger(__name__)

router = APIRouter()
DEFAULT_INSIGHTS_DAYS = 30
DEFAULT_SESSIONS_PAGE_LIMIT = 50
DEFAULT_QUESTIONS_PAGE_LIMIT = 100
DEFAULT_RATINGS_PAGE_LIMIT = 50
DEFAULT_TARGETS_PAGE_LIMIT = 50
DEFAULT_TOP_QUESTIONS = 10
MAX_TOP_QUESTIONS = 50
DEFAULT_FINDING_CASES_PAGE_LIMIT = 50

SourceQuery = Annotated[
    SessionSource | None,
    Query(
        description=(
            "Only conversations of this source: 'user', 'api_key' or 'widget'. "
            "All sources when omitted."
        )
    ),
]
TimezoneQuery = Annotated[
    str,
    Query(
        alias="timezone",
        max_length=64,
        description="IANA time zone for local days; 400 invalid_timezone when unknown.",
    ),
]
StartTimeQuery = Annotated[
    datetime | None,
    Query(
        description="Start of the period, inclusive. Defaults to 30 days before the end."
    ),
]
EndTimeQuery = Annotated[
    datetime | None,
    Query(description="End of the period, exclusive. Defaults to now."),
]


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
    resolved_end = (
        end_date if end_date is not None else now + timedelta(hours=1, minutes=1)
    )
    if resolved_start.tzinfo is None:
        resolved_start = resolved_start.replace(tzinfo=timezone.utc)
    if resolved_end.tzinfo is None:
        resolved_end = resolved_end.replace(tzinfo=timezone.utc)
    return resolved_start, resolved_end


@router.get(
    "/counts/",
    response_model=Counts,
    description="Get total tenant counts.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TENANT_ANALYTICS_ACCESS_REASON,
)
async def get_counts(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Total counts."""
    service = container.analysis_service()
    return await service.get_tenant_counts()


@router.get(
    "/metadata-statistics/",
    response_model=MetadataStatistics,
    description="Get metadata statistics for analytics.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TENANT_ANALYTICS_ACCESS_REASON,
)
async def get_metadata(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
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


@router.get(
    "/assistant-activity/",
    response_model=AssistantActivityStats,
    description="Get assistant activity statistics for the tenant.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TENANT_ANALYTICS_ACCESS_REASON,
)
async def get_assistant_activity(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
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
    "/metadata-statistics/aggregated/",
    response_model=MetadataStatisticsAggregated,
    description="Get aggregated analytics data in hourly buckets.",
    responses=responses.get_responses([400, 403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TENANT_ANALYTICS_ACCESS_REASON,
)
async def get_metadata_aggregated(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    time_zone: Annotated[
        str | None,
        Query(
            max_length=100,
            description="IANA time zone for hourly buckets; omitted uses the database session time zone.",
        ),
    ] = None,
):
    """Aggregated data for analytics (hourly buckets)."""
    if time_zone is not None:
        try:
            ZoneInfo(time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise BadRequestException("Invalid IANA time zone") from error
    start_date, end_date = _default_analytics_range(
        start_date=start_date, end_date=end_date
    )

    service = container.analysis_service()
    assistants, sessions, questions = await service.get_metadata_statistics_aggregated(
        start_date, end_date, time_zone=time_zone
    )

    return analysis_protocol.to_metadata_aggregated(
        assistants=assistants, sessions=sessions, questions=questions
    )


@router.get(
    "/assistants/{assistant_id}/",
    response_model=PaginatedResponse[Message],
    description="Get the questions asked to an assistant within a time range.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_most_recent_questions(
    assistant_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days_since: Annotated[int, Query(ge=0, le=90)] = 30,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
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
    description="Get paginated question history for an assistant.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_most_recent_questions_paginated(
    assistant_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days_since: Annotated[int, Query(ge=0, le=90)] = 30,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_QUESTIONS_PAGE_LIMIT,
    cursor: str | None = None,
    q: str | None = None,
    source: SourceQuery = None,
):
    """Get paginated question history for an assistant.

    Optimized for admin insights history view and large datasets. Questions
    of every source are listed, each tagged with its conversation's source.
    """
    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )
    if q is not None:
        q = q.strip() or None

    service = container.analysis_service()
    items, total_count, next_cursor = await service.get_assistant_question_history_page(
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
        include_followups=include_followups,
        limit=limit,
        query=q,
        cursor=cursor,
        source=source,
    )

    return CursorPaginatedResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        next_cursor=next_cursor,
        previous_cursor=cursor,
    )


@router.get(
    "/assistants/{assistant_id}/feedback/",
    response_model=MessageFeedbackCounts,
    description="Count the good and bad ratings of an assistant's answers within a time range.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_assistant_feedback_counts(
    assistant_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days_since: Annotated[int, Query(ge=0, le=90)] = 30,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    source: SourceQuery = None,
):
    """Count the ratings of the answers `/questions/` lists for the same filters.

    Only per-answer ratings are counted; conversation-level feedback is not.
    """
    from_date, to_date = _normalize_datetime_range(
        from_date=from_date,
        to_date=to_date,
        days_since=days_since,
    )

    service = container.analysis_service()
    return await service.get_assistant_feedback_counts(
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
        include_followups=include_followups,
        source=source,
    )


async def _analysis_answer_stream(
    completion_stream: AsyncIterator[Completion],
) -> AsyncIterator[str]:
    has_answer = False
    async with closing(completion_stream, "analysis stream") as chunks:
        async for chunk in chunks:
            if chunk.response_type == ResponseType.ERROR or chunk.error is not None:
                raise InternalServerException("Analysis generation failed")
            # A sole terminal answer is valid; later terminal text repeats the answer
            # already streamed and otherwise only carries usage.
            if chunk.stop and (has_answer or not chunk.text):
                continue
            has_answer = has_answer or bool(chunk.text)
            yield AnalysisAnswer(answer=chunk.text or "").model_dump_json()


@router.post(
    "/assistants/{assistant_id}/",
    response_model=None,
    description="Ask a question using an assistant's recent questions as context.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def ask_question_about_questions(
    assistant_id: UUID,
    ask_analysis: AskAnalysis,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days_since: Annotated[int, Query(ge=0, le=90)] = 30,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
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
        completion_stream = cast(AsyncIterator[Completion], ai_response.completion)
        return ClosingEventSourceResponse(
            _analysis_answer_stream(completion_stream), closes=[completion_stream]
        )

    completion = ai_response.completion
    if not isinstance(completion, Completion):
        raise ValueError("Expected Completion object for non-streaming response")
    return AnalysisAnswer(answer=completion.text or "")


@router.post(
    "/conversation-insights/",
    response_model=None,
    description="Ask a question about an assistant's or group chat's conversations.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def ask_unified_questions_about_questions(
    ask_analysis: AskAnalysis,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days_since: Annotated[int, Query(ge=0, le=90)] = DEFAULT_INSIGHTS_DAYS,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_followups: bool = False,
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    processing_mode: Annotated[
        AnalysisProcessingMode, Query()
    ] = AnalysisProcessingMode.SYNC,
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
        completion_stream = cast(AsyncIterator[Completion], ai_response.completion)
        return ClosingEventSourceResponse(
            _analysis_answer_stream(completion_stream), closes=[completion_stream]
        )

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
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insights(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    request: Annotated[ConversationInsightRequest, Depends()],
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
        source=request.source,
    )


@router.get(
    "/conversation-insights/jobs/{job_id}/",
    response_model=AnalysisJobStatusResponse,
    description="Get the status of a conversation insights analysis job.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Current insight access to the job's assistant or group chat is required.",
)
async def get_conversation_insight_job(
    job_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    manager = AnalysisJobManager(container.redis_client())
    tenant_id = container.user().tenant_id
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise NotFoundException("Insights analysis job not found")

    await container.analysis_service().authorize_insight_job(job)

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
    response_model=CursorPaginatedResponse[SourcedSessionMetadata],
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_sessions(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: Optional[UUID] = None,
    group_chat_id: Optional[UUID] = None,
    limit: Annotated[Optional[int], Query(ge=1, le=100)] = DEFAULT_SESSIONS_PAGE_LIMIT,
    cursor: Optional[datetime] = None,
    previous: bool = False,
    name_filter: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    source: SourceQuery = None,
):
    """
    Get all sessions for an assistant or group chat in the tenant, from
    every source (users, service API keys, widget visitors) unless `source`
    names one; each carries its source (with insight access).

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
    if limit is None:
        limit = DEFAULT_SESSIONS_PAGE_LIMIT

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
            source=source,
        )
    else:
        assert group_chat_id is not None
        sessions, total = await service.get_group_chat_insight_sessions(
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
            source=source,
        )

    return to_session_metadata_paginated_response(
        sessions=sessions,
        total_count=total,
        limit=limit,
        cursor=cast(datetime, cursor),
        previous=previous,
    )


@router.get(
    "/conversation-insights/sessions/{session_id}/",
    response_model=SourcedSessionPublic,
    responses=responses.get_responses([403, 404, 410]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_session(
    session_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
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
    assert session is not None
    return to_sourced_session_public(session)


_FIGURES_TARGET_DESCRIPTION = (
    "Exactly one of assistant_id or group_chat_id. Conversations of every source "
    "count (users, service API keys, widget visitors) unless source names one; "
    "a conversation counts in the period when it has a question in it."
)


@router.get(
    "/conversation-insights/summary/",
    response_model=InsightSummary,
    description=(
        "Figures for an assistant or group chat over a period, optionally "
        f"beside the previous period of equal length. {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_summary(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
    compare: Annotated[
        bool,
        Query(description="Also return the previous period of equal length."),
    ] = False,
) -> InsightSummary:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_summary(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
        compare=compare,
    )


@router.get(
    "/conversation-insights/activity/",
    response_model=InsightActivity,
    description=(
        "Conversations and questions per local day of an assistant or group "
        f"chat, split by source. {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_activity(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
) -> InsightActivity:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_activity(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
    )


@router.get(
    "/conversation-insights/feedback/",
    response_model=CursorPaginatedResponse[InsightRating],
    description=(
        "Ratings of an assistant's or group chat's answers and conversations, "
        "newest first, never who gave them. An answer rating belongs to the "
        "period of its question, a conversation rating to every period the "
        "conversation had a question in. Pass a page's next_cursor back as "
        f"cursor for the next page. {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_feedback(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    source: SourceQuery = None,
    value: Annotated[
        int | None,
        Query(description="Only good (1) or bad (-1) ratings; 400 for anything else."),
    ] = None,
    has_comment: Annotated[
        bool | None,
        Query(description="Only ratings with (true) or without (false) a comment."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_RATINGS_PAGE_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="The next_cursor of the previous page, as given."),
    ] = None,
) -> CursorPaginatedResponse[InsightRating]:
    if value not in (None, 1, -1):
        raise BadRequestException("value must be 1 or -1")
    window = resolve_window(start_time, end_time, "UTC")
    items, total, next_cursor = await container.insight_figures_service().list_ratings(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
        value=1 if value == 1 else -1 if value == -1 else None,
        has_comment=has_comment,
        limit=limit,
        cursor=cursor,
    )
    return CursorPaginatedResponse(
        items=items,
        total_count=total,
        limit=limit,
        previous_cursor=cursor,
        next_cursor=next_cursor,
    )


@router.get(
    "/conversation-insights/knowledge/",
    response_model=InsightKnowledgeUse,
    description=(
        "Per knowledge source (collection, website or integration knowledge), "
        "the answers of the period that cited at least one passage from it, "
        "injected or fetched through the knowledge tool, and the attached "
        "sources no answer cited; a group chat's attached sources are its "
        "member assistants' together. A target without knowledge gets empty "
        "lists. A refreshed document (a re-crawled page, a re-uploaded file, a "
        "synced integration item) keeps its earlier versions, so its citations "
        "keep counting; when a document is removed (deleted, gone from the "
        "website at a re-crawl, removed at the integration's source), its "
        "citations go with it and are no longer counted. "
        f"{_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_knowledge(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
) -> InsightKnowledgeUse:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_knowledge_use(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
    )


@router.get(
    "/conversation-insights/questions/top/",
    response_model=InsightTopQuestions,
    description=(
        "The commonest questions of the period, grouped by their text after "
        "normalisation (whitespace, letter case and trailing ?!. ignored; "
        "different wordings are different groups), each with how its answers "
        "fared: answers that say they cannot answer (indicative), answer "
        "ratings, and knowledge searched and missed as the summary counts them "
        f"(indicative). {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_top_questions(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_TOP_QUESTIONS, description="Groups to return.")
    ] = DEFAULT_TOP_QUESTIONS,
    include_followups: Annotated[
        bool,
        Query(
            description=(
                "Group every question; by default only each conversation's "
                "opening question."
            )
        ),
    ] = False,
) -> InsightTopQuestions:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_top_questions(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
        limit=limit,
        include_followups=include_followups,
    )


@router.get(
    "/conversation-insights/tools/",
    response_model=InsightToolUsage,
    description=(
        "Tool calls of the period's answers per capability (web search, image "
        "generation and the other purposes, whichever server backs them) or "
        "per server and tool, with failed and denied calls, most called first. "
        "Calls of Eneo's own knowledge server and Skill activations are left "
        "out. An empty list when no answer called a tool. "
        f"{_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_tools(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
) -> InsightToolUsage:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_tool_use(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
    )


@router.get(
    "/conversation-insights/findings/",
    response_model=InsightFindings,
    description=(
        "What to look at in the period, computed from the figures on every "
        "read and stored nowhere: answers that searched the knowledge without "
        "a usable hit, answers that say they cannot answer, conversations "
        "where the person seems to ask again, attached knowledge nobody cited, "
        "bad ratings with comments and tools that often fail. A finding needs "
        "a minimum number of cases and a minimum share; the thresholds are "
        "provisional. Indicative: most signals come from pattern matching or "
        f"stored scores. {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_findings(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
) -> InsightFindings:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().get_findings(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
    )


@router.get(
    "/conversation-insights/findings/{kind}/",
    response_model=InsightFindingCasePage,
    description=(
        "The cases behind one finding, a page at a time, in the order the "
        "finding's examples come in: knowledge_missed and unanswered list "
        "answers newest first, rephrasing lists conversations with similar "
        "consecutive questions first. Listed whether or not the finding "
        "passes its thresholds; knowledge_missed is empty for a target without "
        "knowledge. Pass a page's next_cursor back as cursor for the next "
        f"page. {_FIGURES_TARGET_DESCRIPTION}"
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RESOURCE_INSIGHTS_ACCESS_REASON,
)
async def get_conversation_insight_finding_cases(
    kind: FindingCaseKind,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    time_zone: TimezoneQuery = "UTC",
    source: SourceQuery = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_FINDING_CASES_PAGE_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="The next_cursor of the previous page, as given."),
    ] = None,
) -> InsightFindingCasePage:
    window = resolve_window(start_time, end_time, time_zone)
    return await container.insight_figures_service().list_finding_cases(
        kind,
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        window=window,
        source=source,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/targets/",
    response_model=InsightTargetPage,
    description=(
        "Every assistant people see and every group chat of the tenant with its "
        "usage in the period: conversations by source and questions, the "
        "previous period of equal length when compare is set, and answer "
        "ratings where insights are on (usage only where they are off). A "
        "conversation counts when it has a question in the period. totals sum "
        "the usage of every target that matches the filters, not only the page."
    ),
    responses=responses.get_responses([400, 403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TENANT_ANALYTICS_ACCESS_REASON,
)
async def get_insight_targets(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    start_time: StartTimeQuery = None,
    end_time: EndTimeQuery = None,
    compare: Annotated[
        bool,
        Query(description="Also return each target's previous period."),
    ] = False,
    sort: TargetSort = "conversations",
    order: Literal["asc", "desc"] = "desc",
    q: Annotated[
        str | None, Query(max_length=200, description="Part of the name.")
    ] = None,
    activity: Annotated[
        Literal["all", "unused"],
        Query(
            description="'unused': only targets without conversations in the period."
        ),
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_TARGETS_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InsightTargetPage:
    window = resolve_window(start_time, end_time, "UTC")
    return await container.insight_figures_service().list_targets(
        window=window,
        compare=compare,
        query=(q.strip() or None) if q is not None else None,
        unused_only=activity == "unused",
        sort=sort,
        descending=order == "desc",
        offset=offset,
        limit=limit,
    )
