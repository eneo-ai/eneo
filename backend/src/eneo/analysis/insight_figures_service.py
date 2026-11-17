"""The insights figures: a period's summary, activity per day, the ratings
inbox and the tenant's list of assistants and group chats.

Every read about one assistant or group chat asks
``AnalysisService.assert_insight_access`` first, the same decision the
insights chat asks; the tenant's list needs the insights permission, like the
other tenant analytics. The figures are counted from live rows on every read,
so they are no copies of conversations and register no derivations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from eneo.analysis.analysis import (
    AnswerRatingCounts,
    ConversationRatingCounts,
    InsightActivity,
    InsightActivityDay,
    InsightPeriodSummary,
    InsightRating,
    InsightSummary,
    InsightTarget,
    InsightTargetPage,
    InsightTargetUsage,
    KnowledgeUse,
    MessageFeedbackCounts,
    SourceCounts,
)
from eneo.analysis.analysis_service import AnalysisService
from eneo.analysis.insight_exceptions import InvalidTimezoneError
from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    InsightsRepository,
    PeriodFigures,
    TargetSort,
    TargetUsage,
)
from eneo.analysis.insights_repo import SourceCounts as SourceCountsRow
from eneo.main.exceptions import BadRequestException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.sessions.session_source import SessionSource
from eneo.users.user import UserInDB

DEFAULT_PERIOD = timedelta(days=30)


def resolve_window(
    start: datetime | None,
    end: datetime | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> InsightWindow:
    """The half-open ``[start, end)`` period a request asks about.

    Without an end the period ends now, without a start it is the 30 days
    before its end. A time without a zone is UTC.
    """
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise InvalidTimezoneError(timezone_name)
    resolved_end = end if end is not None else (now or datetime.now(timezone.utc))
    resolved_start = start if start is not None else resolved_end - DEFAULT_PERIOD
    if resolved_start.tzinfo is None:
        resolved_start = resolved_start.replace(tzinfo=timezone.utc)
    if resolved_end.tzinfo is None:
        resolved_end = resolved_end.replace(tzinfo=timezone.utc)
    if resolved_start >= resolved_end:
        raise BadRequestException("start_time must be before end_time")
    return InsightWindow(start=resolved_start, end=resolved_end, timezone=timezone_name)


def previous_window(window: InsightWindow) -> InsightWindow:
    """The period of equal length that ends where ``window`` starts."""
    length = window.end - window.start
    return InsightWindow(
        start=window.start - length, end=window.start, timezone=window.timezone
    )


def encode_cursor(at: datetime, key: UUID) -> str:
    return f"{at.isoformat()}|{key}"


def decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    at_raw, separator, key_raw = cursor.partition("|")
    if not separator:
        raise BadRequestException("Invalid cursor format")
    try:
        at = datetime.fromisoformat(at_raw)
        key = UUID(key_raw)
    except ValueError as exc:
        raise BadRequestException("Invalid cursor") from exc
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at, key


def _counts(row: SourceCountsRow) -> SourceCounts:
    return SourceCounts(
        total=row.total, user=row.user, api_key=row.api_key, widget=row.widget
    )


def _period(window: InsightWindow, figures: PeriodFigures) -> InsightPeriodSummary:
    return InsightPeriodSummary(
        start=window.start,
        end=window.end,
        conversations=_counts(figures.conversations),
        questions=_counts(figures.questions),
        followups=figures.followups,
        users=figures.users,
        single_question_conversations=figures.single_question_conversations,
        returning_users=figures.returning_users,
        unanswered=figures.unanswered,
        knowledge=(
            KnowledgeUse(
                searched=figures.knowledge.searched, missed=figures.knowledge.missed
            )
            if figures.knowledge is not None
            else None
        ),
        answer_ratings=AnswerRatingCounts(
            positive=figures.answers_positive,
            negative=figures.answers_negative,
            with_comment=figures.answers_with_comment,
        ),
        conversation_ratings=ConversationRatingCounts(
            positive=figures.conversations_positive,
            negative=figures.conversations_negative,
        ),
    )


def _usage(usage: TargetUsage) -> InsightTargetUsage:
    return InsightTargetUsage(
        conversations=_counts(usage.conversations), questions=usage.questions
    )


class InsightFiguresService:
    def __init__(
        self,
        user: UserInDB,
        analysis_service: AnalysisService,
        insights_repo: InsightsRepository,
    ):
        self.user = user
        self.analysis_service = analysis_service
        self.repo = insights_repo

    async def _scope(
        self, *, assistant_id: UUID | None, group_chat_id: UUID | None
    ) -> InsightScope:
        if (assistant_id is None) == (group_chat_id is None):
            raise BadRequestException(
                "Provide exactly one of assistant_id or group_chat_id"
            )
        await self.analysis_service.assert_insight_access(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        if assistant_id is not None:
            return InsightScope("assistant", assistant_id, self.user.tenant_id)
        assert group_chat_id is not None
        return InsightScope("group_chat", group_chat_id, self.user.tenant_id)

    async def get_summary(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
        compare: bool,
    ) -> InsightSummary:
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        knowledge = await self.repo.knowledge_setup(scope)
        period = await self.repo.summarize(
            scope, window, source=source, knowledge=knowledge
        )
        previous = None
        if compare:
            before = previous_window(window)
            previous = _period(
                before,
                await self.repo.summarize(
                    scope, before, source=source, knowledge=knowledge
                ),
            )
        return InsightSummary(
            timezone=window.timezone,
            source=source,
            period=_period(window, period),
            previous=previous,
        )

    async def get_activity(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
    ) -> InsightActivity:
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        days = await self.repo.count_activity(scope, window, source=source)
        return InsightActivity(
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            days=[
                InsightActivityDay(
                    date=day.day,
                    conversations=_counts(day.conversations),
                    questions=_counts(day.questions),
                )
                for day in days
            ],
        )

    async def list_ratings(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
        value: Literal[-1, 1] | None,
        has_comment: bool | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[InsightRating], int, str | None]:
        """A page of ratings, newest first, with the total and the next
        page's cursor."""
        after = decode_cursor(cursor)
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        rows, total, has_more = await self.repo.list_ratings(
            scope,
            window,
            source=source,
            value=value,
            has_comment=has_comment,
            limit=limit,
            after=after,
        )
        next_cursor = (
            encode_cursor(rows[-1].rated_at, rows[-1].key)
            if has_more and rows
            else None
        )
        return (
            [
                InsightRating(
                    kind=row.kind,
                    value=1 if row.value == 1 else -1,
                    comment=row.comment,
                    question=row.question,
                    question_id=row.question_id,
                    session_id=row.session_id,
                    source=row.source,
                    created_at=row.rated_at,
                )
                for row in rows
            ],
            total,
            next_cursor,
        )

    @validate_permissions(Permission.INSIGHTS)
    async def list_targets(
        self,
        *,
        window: InsightWindow,
        compare: bool,
        query: str | None,
        unused_only: bool,
        sort: TargetSort,
        descending: bool,
        offset: int,
        limit: int,
    ) -> InsightTargetPage:
        rows, total = await self.repo.list_targets(
            tenant_id=self.user.tenant_id,
            window=window,
            previous=previous_window(window) if compare else None,
            query=query,
            unused_only=unused_only,
            sort=sort,
            descending=descending,
            offset=offset,
            limit=limit,
        )
        return InsightTargetPage(
            items=[
                InsightTarget(
                    id=row.id,
                    kind=row.kind,
                    name=row.name,
                    space_id=row.space_id,
                    space_name=row.space_name,
                    personal_space=row.personal_space,
                    insight_enabled=row.insight_enabled,
                    conversations=_counts(row.usage.conversations),
                    questions=row.usage.questions,
                    previous=_usage(row.previous) if compare else None,
                    # A target with insights off shows usage only.
                    ratings=(
                        MessageFeedbackCounts(
                            positive=row.answers_positive,
                            negative=row.answers_negative,
                        )
                        if row.insight_enabled
                        else None
                    ),
                )
                for row in rows
            ],
            total_count=total,
            limit=limit,
            offset=offset,
        )
