"""The insights figures: a period's summary, activity per day, the ratings
inbox, knowledge use, the commonest questions, tool use, the findings and
their cases, and the tenant's list of assistants and group chats.

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
    InsightFinding,
    InsightFindingCase,
    InsightFindingCasePage,
    InsightFindingExample,
    InsightFindings,
    InsightKnowledgeSource,
    InsightKnowledgeUse,
    InsightPeriodSummary,
    InsightPersonalUsage,
    InsightQuestionGroup,
    InsightRating,
    InsightSummary,
    InsightTarget,
    InsightTargetCounts,
    InsightTargetPage,
    InsightTargetTotals,
    InsightTargetUsage,
    InsightTargetUsers,
    InsightToolUsage,
    InsightToolUse,
    InsightTopQuestions,
    KnowledgeMissCase,
    KnowledgeUse,
    MessageFeedbackCounts,
    RephrasingCase,
    SourceCounts,
    UnansweredCase,
)
from eneo.analysis.analysis_service import AnalysisService
from eneo.analysis.insight_exceptions import InvalidTimezoneError
from eneo.analysis.insight_findings import (
    Finding,
    FindingInputs,
    find_findings,
)
from eneo.analysis.insight_scope import FindingCaseKind, InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    InsightsRepository,
    KnowledgeSetup,
    KnowledgeSourceRow,
    PeriodFigures,
    TargetSort,
    TargetUsage,
    ToolUseRow,
)
from eneo.analysis.insights_repo import SourceCounts as SourceCountsRow
from eneo.main.exceptions import BadRequestException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.sessions.session_source import SessionSource
from eneo.users.user import UserInDB

DEFAULT_PERIOD = timedelta(days=30)
# Examples a finding carries; its cases route lists the rest.
FINDING_EXAMPLES = 3


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


def encode_offset_cursor(offset: int) -> str:
    return f"o{offset}"


def decode_offset_cursor(cursor: str | None) -> int:
    """The offset a page cursor of a ranked list carries; 0 without one."""
    if not cursor:
        return 0
    digits = cursor[1:] if cursor.startswith("o") else ""
    if not digits.isdigit():
        raise BadRequestException("Invalid cursor")
    return int(digits)


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
            negative_with_comment=figures.answers_negative_with_comment,
        ),
        conversation_ratings=ConversationRatingCounts(
            positive=figures.conversations_positive,
            negative=figures.conversations_negative,
            with_comment=figures.conversations_with_comment,
            negative_with_comment=figures.conversations_negative_with_comment,
        ),
    )


def _usage(usage: TargetUsage) -> InsightTargetUsage:
    return InsightTargetUsage(
        conversations=_counts(usage.conversations), questions=usage.questions
    )


def _knowledge_source(row: KnowledgeSourceRow) -> InsightKnowledgeSource:
    return InsightKnowledgeSource(
        kind=row.kind,
        id=row.id,
        name=row.name,
        attached=row.attached,
        answers=row.answers,
    )


def _rating(value: int | None) -> Literal[-1, 1] | None:
    if value is None:
        return None
    return 1 if value == 1 else -1


def _example(
    question: str,
    question_id: UUID | None,
    session_id: UUID,
    source: SessionSource,
    comment: str | None = None,
) -> InsightFindingExample:
    return InsightFindingExample(
        question=question,
        question_id=question_id,
        session_id=session_id,
        source=source,
        comment=comment,
    )


def _tool(row: ToolUseRow) -> InsightToolUse:
    return InsightToolUse(
        kind="capability" if row.purpose is not None else "tool",
        purpose=row.purpose,
        server_name=row.server_name,
        tool_name=row.tool_name,
        title=row.title,
        calls=row.calls,
        failed=row.failed,
        denied=row.denied,
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

    async def get_knowledge_use(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
    ) -> InsightKnowledgeUse:
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        citations = await self.repo.knowledge_citations(scope, window, source=source)
        return InsightKnowledgeUse(
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            answers=citations.answers,
            citing_answers=citations.citing_answers,
            sources=[_knowledge_source(row) for row in citations.cited],
            unused=[_knowledge_source(row) for row in citations.unused],
        )

    async def get_top_questions(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
        limit: int,
        include_followups: bool,
    ) -> InsightTopQuestions:
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        knowledge = await self.repo.knowledge_setup(scope)
        rows, total = await self.repo.question_groups(
            scope,
            window,
            source=source,
            knowledge=knowledge,
            n=limit,
            include_followups=include_followups,
        )
        return InsightTopQuestions(
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            include_followups=include_followups,
            total_questions=total,
            groups=[
                InsightQuestionGroup(
                    question=row.display_text,
                    occurrences=row.occurrences,
                    share=row.occurrences / total if total else 0.0,
                    conversations=row.conversations,
                    unanswered=row.unanswered,
                    ratings=MessageFeedbackCounts(
                        positive=row.answers_positive, negative=row.answers_negative
                    ),
                    knowledge=(
                        KnowledgeUse(
                            searched=row.knowledge.searched,
                            missed=row.knowledge.missed,
                        )
                        if row.knowledge is not None
                        else None
                    ),
                    sample_session_id=row.sample_session_id,
                )
                for row in rows
            ],
        )

    async def get_tool_use(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
    ) -> InsightToolUsage:
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        rows = await self.repo.tool_use(scope, window, source=source)
        return InsightToolUsage(
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            tools=[_tool(row) for row in rows],
        )

    async def get_findings(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
    ) -> InsightFindings:
        """The period's findings (:mod:`eneo.analysis.insight_findings`), each
        with up to :data:`FINDING_EXAMPLES` examples."""
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        knowledge = await self.repo.knowledge_setup(scope)
        figures = await self.repo.summarize(
            scope, window, source=source, knowledge=knowledge
        )
        rephrasing, rephrasing_total = await self.repo.find_rephrasing(
            scope, window, offset=0, limit=FINDING_EXAMPLES, source=source
        )
        findings = find_findings(
            FindingInputs(
                figures=figures,
                rephrasing=rephrasing_total,
                knowledge=await self.repo.knowledge_citations(
                    scope, window, source=source
                ),
                tools=await self.repo.tool_use(scope, window, source=source),
            )
        )
        result: list[InsightFinding] = []
        for finding in findings:
            examples = (
                [
                    _example(
                        row.questions[0],
                        row.question_ids[0],
                        row.session_id,
                        row.source,
                    )
                    for row in rephrasing
                    if row.questions
                ]
                if finding.kind == "rephrasing"
                else await self._finding_examples(
                    finding, scope, window, source=source, knowledge=knowledge
                )
            )
            result.append(
                InsightFinding(
                    kind=finding.kind,
                    affected=finding.affected,
                    base=finding.base,
                    examples=examples,
                    sources=(
                        [_knowledge_source(row) for row in finding.sources]
                        if finding.kind == "knowledge_unused"
                        else None
                    ),
                    tool=_tool(finding.tool) if finding.tool is not None else None,
                )
            )
        return InsightFindings(
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            findings=result,
        )

    async def _finding_examples(
        self,
        finding: Finding,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
        knowledge: KnowledgeSetup,
    ) -> list[InsightFindingExample]:
        if finding.kind == "knowledge_missed":
            missed, _, _ = await self.repo.find_no_knowledge(
                scope,
                window,
                offset=0,
                limit=FINDING_EXAMPLES,
                source=source,
                absolute=knowledge,
            )
            return [
                _example(row.question, row.question_id, row.session_id, row.source)
                for row in missed
            ]
        if finding.kind == "unanswered":
            unanswered, _ = await self.repo.find_unanswered(
                scope, window, offset=0, limit=FINDING_EXAMPLES, source=source
            )
            return [
                _example(row.question, row.question_id, row.session_id, row.source)
                for row in unanswered
            ]
        if finding.kind == "negative_ratings":
            ratings, _, _ = await self.repo.list_ratings(
                scope,
                window,
                source=source,
                value=-1,
                has_comment=True,
                limit=FINDING_EXAMPLES,
                after=None,
            )
            return [
                _example(
                    row.question,
                    row.question_id,
                    row.session_id,
                    row.source,
                    row.comment,
                )
                for row in ratings
            ]
        return []

    async def list_finding_cases(
        self,
        kind: FindingCaseKind,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        window: InsightWindow,
        source: SessionSource | None,
        limit: int,
        cursor: str | None,
    ) -> InsightFindingCasePage:
        """A page of one finding's cases, in the order the finding's examples
        come in, whether or not the finding passes its thresholds."""
        offset = decode_offset_cursor(cursor)
        scope = await self._scope(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        items: list[InsightFindingCase] = []
        if kind == "knowledge_missed":
            knowledge = await self.repo.knowledge_setup(scope)
            total = 0
            if knowledge.has_knowledge:
                missed, total, _ = await self.repo.find_no_knowledge(
                    scope,
                    window,
                    offset=offset,
                    limit=limit,
                    source=source,
                    absolute=knowledge,
                )
                items = [
                    KnowledgeMissCase(
                        kind="knowledge_missed",
                        question_id=row.question_id,
                        question=row.question,
                        session_id=row.session_id,
                        source=row.source,
                        created_at=row.created_at,
                        reason=row.reason,
                        best_score=row.best_score,
                        rating=_rating(row.rating),
                    )
                    for row in missed
                ]
        elif kind == "unanswered":
            unanswered, total = await self.repo.find_unanswered(
                scope, window, offset=offset, limit=limit, source=source
            )
            items = [
                UnansweredCase(
                    kind="unanswered",
                    question_id=row.question_id,
                    question=row.question,
                    session_id=row.session_id,
                    source=row.source,
                    created_at=row.created_at,
                    phrase=row.evidence,
                    rating=_rating(row.rating),
                )
                for row in unanswered
            ]
        else:
            rephrasing, total = await self.repo.find_rephrasing(
                scope, window, offset=offset, limit=limit, source=source
            )
            items = [
                RephrasingCase(
                    kind="rephrasing",
                    session_id=row.session_id,
                    source=row.source,
                    started_at=row.started_at,
                    questions=row.questions,
                    question_ids=row.question_ids,
                    similar_pairs=row.similar_pairs,
                )
                for row in rephrasing
            ]
        shown_to = offset + len(items)
        return InsightFindingCasePage(
            kind=kind,
            timezone=window.timezone,
            source=source,
            start=window.start,
            end=window.end,
            items=items,
            total_count=total,
            limit=limit,
            next_cursor=(
                encode_offset_cursor(shown_to) if items and shown_to < total else None
            ),
        )

    @validate_permissions(Permission.INSIGHTS)
    async def get_tenant_activity(self, *, window: InsightWindow) -> InsightActivity:
        """Conversations and questions per local day over every target people
        see, by the rules of :meth:`list_targets`."""
        days = await self.repo.count_tenant_activity(
            tenant_id=self.user.tenant_id, window=window
        )
        return InsightActivity(
            timezone=window.timezone,
            source=None,
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
        listing = await self.repo.list_targets(
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
        totals, personal = listing.totals, listing.personal
        return InsightTargetPage(
            items=[
                InsightTarget(
                    id=row.id,
                    kind=row.kind,
                    name=row.name,
                    space_id=row.space_id,
                    space_name=row.space_name,
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
                for row in listing.rows
            ],
            total_count=listing.total,
            limit=limit,
            offset=offset,
            totals=InsightTargetTotals(
                conversations=_counts(totals.usage.conversations),
                questions=totals.usage.questions,
                previous=_usage(totals.previous) if compare else None,
            ),
            personal=(
                InsightPersonalUsage(
                    assistants=personal.targets,
                    conversations=_counts(personal.usage.conversations),
                    questions=personal.usage.questions,
                    previous=_usage(personal.previous) if compare else None,
                )
                if personal is not None
                else None
            ),
            counts=InsightTargetCounts(
                all=listing.counts.all, unused=listing.counts.unused
            ),
            users=InsightTargetUsers(
                current=listing.users.current,
                previous=listing.users.previous if compare else None,
            ),
        )
