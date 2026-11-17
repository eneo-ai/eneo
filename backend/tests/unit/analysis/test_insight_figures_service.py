"""The insights figures service: the period a request asks about, the access
decision before any read, and what a target with insights off shows."""

from datetime import datetime, timedelta, timezone
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
    encode_cursor,
    previous_window,
    resolve_window,
)
from eneo.analysis.insight_scope import InsightWindow
from eneo.analysis.insights_repo import (
    KnowledgeSetup,
    PeriodFigures,
    SourceCounts,
    TargetRow,
    TargetUsage,
)
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.roles.permissions import Permission

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
NONE = SourceCounts(0, 0, 0, 0)


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


async def test_the_summary_asks_access_first_and_compares_with_the_period_before():
    service, access, repo = _service()
    assistant_id = uuid4()
    window = InsightWindow(NOW - timedelta(days=7), NOW, "UTC")
    repo.knowledge_setup.return_value = KnowledgeSetup(False, frozenset())
    repo.summarize.return_value = PeriodFigures(
        NONE, NONE, 0, 0, 0, 0, 0, None, 0, 0, 0, 0, 0
    )

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
    denied_repo.list_targets.assert_not_awaited()

    service, _, repo = _service(permissions=[Permission.INSIGHTS])
    usage = TargetUsage(SourceCounts(3, 1, 0, 2), 4)

    def row(insight_enabled: bool) -> TargetRow:
        return TargetRow(
            uuid4(), "assistant", "a", uuid4(), "s", False, insight_enabled,
            usage, usage, 2, 1,
        )  # fmt: skip

    repo.list_targets.return_value = ([row(True), row(False)], 2)

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
