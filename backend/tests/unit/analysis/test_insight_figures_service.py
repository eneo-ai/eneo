"""The insights figures service: the period a request asks about, the access
decision before any read, and what a target with insights off shows."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.analysis.analysis_service import AnalysisService
from eneo.analysis.insight_exceptions import InvalidTimezoneError
from eneo.analysis.insight_figures_service import (
    InsightFiguresService,
    decode_cursor,
    decode_offset_cursor,
    encode_cursor,
    encode_offset_cursor,
    previous_window,
    resolve_window,
)
from eneo.analysis.insight_scope import InsightWindow
from eneo.analysis.insights_repo import (
    ActivityDay,
    KnowledgeCitations,
    KnowledgeSetup,
    KnowledgeUse,
    PeriodFigures,
    PersonalUsage,
    RephrasingRow,
    SourceCounts,
    TargetCounts,
    TargetListing,
    TargetRow,
    TargetTotals,
    TargetUsage,
    TargetUsers,
    UnansweredRow,
)
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.roles.permissions import Permission

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
NONE = SourceCounts(0, 0, 0, 0)


def _figures(**overrides: Any) -> PeriodFigures:
    fields: dict[str, Any] = {name: 0 for name in PeriodFigures._fields}
    fields.update(conversations=NONE, questions=NONE, knowledge=None)
    fields.update(overrides)
    return PeriodFigures(**fields)


def _service(*, permissions: list[Permission] | None = None):
    user = SimpleNamespace(tenant_id=uuid4(), permissions=permissions or [])
    access, repo = AsyncMock(spec=AnalysisService), AsyncMock()
    service = InsightFiguresService(
        user=cast(Any, user),
        analysis_service=cast(Any, access),
        insights_repo=cast(Any, repo),
    )
    return service, access, repo


def test_the_period_defaults_to_the_30_days_before_now():
    window = resolve_window(None, None, "Europe/Stockholm", now=NOW)

    assert window == InsightWindow(NOW - timedelta(days=30), NOW, "Europe/Stockholm")
    naive = resolve_window(datetime(2026, 9, 1), datetime(2026, 9, 2), "UTC")
    assert naive.start.tzinfo is timezone.utc and naive.end.tzinfo is timezone.utc


def test_the_period_needs_a_known_zone_and_a_length():
    with pytest.raises(InvalidTimezoneError):
        resolve_window(None, None, "Mars/Olympus", now=NOW)
    with pytest.raises(BadRequestException):
        resolve_window(NOW, NOW, "UTC")


def test_the_previous_period_is_as_long_and_ends_where_the_period_starts():
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")

    assert previous_window(window) == InsightWindow(
        NOW - timedelta(days=14), NOW - timedelta(days=7), "UTC"
    )


def test_a_cursor_reads_back_and_garbage_is_refused():
    key = uuid4()

    assert decode_cursor(encode_cursor(NOW, key)) == (NOW, key)
    assert decode_cursor(None) is None
    for garbage in ("no-separator", "not-a-time|" + str(key), f"{NOW.isoformat()}|x"):
        with pytest.raises(BadRequestException):
            decode_cursor(garbage)
    assert decode_offset_cursor(encode_offset_cursor(50)) == 50
    assert decode_offset_cursor(None) == 0
    for garbage in ("50", "o-1", "ox", NOW.isoformat()):
        with pytest.raises(BadRequestException):
            decode_offset_cursor(garbage)


async def test_the_summary_asks_access_first_and_compares_with_the_period_before():
    service, access, repo = _service()
    assistant_id = uuid4()
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")
    repo.knowledge_setup.return_value = KnowledgeSetup(False, frozenset())
    repo.summarize.return_value = _figures()

    summary = await service.get_summary(
        assistant_id=assistant_id,
        group_chat_id=None,
        window=window,
        source="widget",
        compare=True,
    )

    access.assert_insight_access.assert_awaited_once_with(
        assistant_id=assistant_id, group_chat_id=None
    )
    assert [call.args[1] for call in repo.summarize.await_args_list] == [
        window,
        previous_window(window),
    ]
    assert summary.source == "widget"
    assert summary.previous is not None and summary.period.knowledge is None


async def test_a_read_is_refused_before_it_reads():
    service, access, repo = _service()
    access.assert_insight_access.side_effect = UnauthorizedException("off")
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")

    with pytest.raises(UnauthorizedException):
        await service.get_activity(
            assistant_id=uuid4(), group_chat_id=None, window=window, source=None
        )
    with pytest.raises(BadRequestException):
        await service.get_activity(
            assistant_id=None, group_chat_id=None, window=window, source=None
        )
    repo.count_activity.assert_not_awaited()


async def test_targets_need_the_insights_permission_and_insights_off_shows_usage():
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")
    denied, _, denied_repo = _service()
    with pytest.raises(UnauthorizedException):
        await denied.list_targets(
            window=window,
            compare=False,
            query=None,
            unused_only=False,
            sort="name",
            descending=False,
            offset=0,
            limit=10,
        )
    with pytest.raises(UnauthorizedException):
        await denied.get_tenant_activity(window=window)
    denied_repo.list_targets.assert_not_awaited()
    denied_repo.count_tenant_activity.assert_not_awaited()

    service, _, repo = _service(permissions=[Permission.INSIGHTS])
    usage = TargetUsage(SourceCounts(3, 1, 0, 2), 4)

    def row(insight_enabled: bool) -> TargetRow:
        return TargetRow(
            uuid4(), "assistant", "a", uuid4(), "s", insight_enabled,
            usage, usage, 2, 1,
        )  # fmt: skip

    personal = PersonalUsage(3, TargetUsage(SourceCounts(2, 2, 0, 0), 5), usage)
    repo.list_targets.return_value = TargetListing(
        [row(True), row(False)],
        2,
        TargetTotals(usage, TargetUsage(SourceCounts(1, 1, 0, 0), 1)),
        personal,
        TargetCounts(all=41, unused=18),
        TargetUsers(current=7, previous=4),
    )

    page = await service.list_targets(
        window=window,
        compare=False,
        query=None,
        unused_only=False,
        sort="conversations",
        descending=True,
        offset=0,
        limit=10,
    )

    assert repo.list_targets.await_args.kwargs["previous"] is None
    enabled, disabled = page.items
    assert enabled.ratings is not None and enabled.ratings.negative == 1
    assert disabled.ratings is None
    assert disabled.conversations.widget == 2 and enabled.previous is None
    assert page.totals.conversations.widget == 2 and page.totals.previous is None
    assert page.personal is not None
    assert (page.personal.assistants, page.personal.questions) == (3, 5)
    assert page.personal.previous is None
    assert (page.counts.all, page.counts.unused) == (41, 18)
    # The previous period's users only when compared.
    assert (page.users.current, page.users.previous) == (7, None)

    repo.list_targets.return_value = TargetListing(
        [], 0, TargetTotals(usage, usage), None, TargetCounts(0, 0), TargetUsers(2, 1)
    )
    without = await service.list_targets(
        window=window,
        compare=True,
        query=None,
        unused_only=False,
        sort="name",
        descending=False,
        offset=0,
        limit=10,
    )
    assert without.personal is None and without.totals.previous is not None
    assert (without.users.current, without.users.previous) == (2, 1)

    # The organisation's days, of every source, for the caller's tenant.
    repo.count_tenant_activity.return_value = [
        ActivityDay(
            date(2026, 11, 16), SourceCounts(2, 1, 0, 1), SourceCounts(3, 2, 0, 1)
        )
    ]
    activity = await service.get_tenant_activity(window=window)
    assert (activity.source, activity.timezone) == (None, "UTC")
    assert [
        (d.date, d.conversations.widget, d.questions.total) for d in activity.days
    ] == [(date(2026, 11, 16), 1, 3)]
    assert repo.count_tenant_activity.await_args.kwargs == {
        "tenant_id": service.user.tenant_id,
        "window": window,
    }


async def test_findings_carry_examples_only_for_what_passes_the_thresholds():
    service, access, repo = _service()
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")
    session_id, first_question = uuid4(), uuid4()
    repo.knowledge_setup.return_value = KnowledgeSetup(True, frozenset())
    # 12 of 40 answers cannot answer; knowledge missed 3 of 30 (below 10 cases).
    repo.summarize.return_value = _figures(
        conversations=SourceCounts(40, 40, 0, 0),
        questions=SourceCounts(40, 40, 0, 0),
        unanswered=12,
        knowledge=KnowledgeUse(searched=30, missed=3),
    )
    repo.find_rephrasing.return_value = (
        [
            RephrasingRow(
                session_id,
                NOW,
                ["a?", "a igen?"],
                1,
                [first_question, uuid4()],
                "widget",
            )
        ],
        1,
    )
    repo.knowledge_citations.return_value = KnowledgeCitations(40, 30, [], [])
    repo.tool_use.return_value = []
    repo.find_unanswered.return_value = (
        [
            UnansweredRow(
                uuid4(), NOW, session_id, "Vad kostar det?", "vet inte", "user", None
            )
        ],
        12,
    )

    findings = await service.get_findings(
        assistant_id=uuid4(), group_chat_id=None, window=window, source="user"
    )

    access.assert_insight_access.assert_awaited_once()
    assert [(f.kind, f.affected, f.base) for f in findings.findings] == [
        ("unanswered", 12, 40)
    ]
    assert [e.question for e in findings.findings[0].examples] == ["Vad kostar det?"]
    assert repo.find_unanswered.await_args.kwargs["source"] == "user"
    repo.find_no_knowledge.assert_not_awaited()
    repo.list_ratings.assert_not_awaited()


async def test_finding_cases_page_with_an_offset_cursor_and_need_knowledge():
    service, _, repo = _service()
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")
    repo.knowledge_setup.return_value = KnowledgeSetup(False, frozenset())

    no_knowledge = await service.list_finding_cases(
        "knowledge_missed",
        assistant_id=uuid4(),
        group_chat_id=None,
        window=window,
        source=None,
        limit=10,
        cursor=None,
    )

    assert (no_knowledge.items, no_knowledge.total_count) == ([], 0)
    repo.find_no_knowledge.assert_not_awaited()

    row = UnansweredRow(uuid4(), NOW, uuid4(), "Q", "vet inte", "api_key", -1)
    repo.find_unanswered.return_value = ([row, row], 5)
    page = await service.list_finding_cases(
        "unanswered",
        assistant_id=uuid4(),
        group_chat_id=None,
        window=window,
        source=None,
        limit=2,
        cursor=encode_offset_cursor(2),
    )

    assert repo.find_unanswered.await_args.kwargs["offset"] == 2
    assert page.next_cursor == encode_offset_cursor(4)
    assert (page.items[0].kind, page.items[0].phrase, page.items[0].rating) == (
        "unanswered",
        "vet inte",
        -1,
    )
