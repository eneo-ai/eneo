"""Unit tests for the loopback insights MCP server.

Covers scope resolution from the token, window validation, the self-capped
page formatting each tool emits, the tools themselves against a fake
repository, and the ephemeral-server builder.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    QuestionRow,
    TopQuestionRow,
    UsageBucket,
    UsageSummary,
)
from eneo.internal_mcp import insights
from eneo.internal_mcp.foundation import fit_lines
from eneo.internal_mcp.insights import (
    INSIGHTS_SERVER_NAME,
    MAX_WINDOW_DAYS,
    _bucket_count,
    _list_questions_text,
    _parse_window,
    _top_questions_text,
    _usage_summary_text,
    build_insights_mcp_server,
    list_questions,
    mcp,
    target_label,
    top_questions,
    usage_summary,
)
from eneo.internal_mcp.registry import internal_mcp_mounts

STOCKHOLM = "Europe/Stockholm"
START = "2026-09-01T00:00:00+02:00"
END = "2026-09-08T00:00:00+02:00"


def _window(start=START, end=END, tz=STOCKHOLM) -> InsightWindow:
    return _parse_window(start, end, tz)


class TestParseWindow:
    def test_valid_window(self):
        window = _window()

        assert window.start == datetime.fromisoformat(START)
        assert window.end == datetime.fromisoformat(END)
        assert window.timezone == STOCKHOLM

    @pytest.mark.parametrize(
        "start,end,tz,fragment",
        [
            ("2026-09-01T00:00:00", END, STOCKHOLM, "UTC offset"),
            (START, "2026-09-08", STOCKHOLM, "UTC offset"),
            ("not a date", END, STOCKHOLM, "ISO-8601"),
            (END, START, STOCKHOLM, "after start"),
            (START, START, STOCKHOLM, "after start"),
            (START, END, "Mars/Olympus", "Unknown timezone"),
            (
                START,
                (
                    datetime.fromisoformat(START) + timedelta(days=MAX_WINDOW_DAYS + 1)
                ).isoformat(),
                STOCKHOLM,
                "spans more than",
            ),
        ],
    )
    def test_rejections(self, start, end, tz, fragment):
        with pytest.raises(ValueError, match=fragment):
            _parse_window(start, end, tz)


class TestBucketCount:
    def test_days_weeks_months(self):
        window = _window("2026-01-01T00:00:00+01:00", "2026-12-31T00:00:00+01:00")

        assert _bucket_count(window, "day") == 365
        assert _bucket_count(window, "week") == 53
        assert _bucket_count(window, "month") == 12

    @pytest.mark.asyncio
    async def test_usage_summary_refuses_too_many_buckets_before_querying(self):
        text = await usage_summary(
            ctx=None,
            start="2026-01-01T00:00:00+01:00",
            end="2026-12-31T00:00:00+01:00",
            timezone=STOCKHOLM,
            granularity="day",
        )

        assert "coarser granularity" in text

    @pytest.mark.asyncio
    async def test_tools_return_window_errors_as_text(self):
        text = await list_questions(ctx=None, start=END, end=START)

        assert "end must be after start" in text


class TestFitLines:
    def test_cuts_by_characters_and_keeps_order(self):
        lines = ["a" * 10, "b" * 10, "c" * 10]

        assert fit_lines(lines, budget=25) == lines[:2]

    def test_always_keeps_the_first_line(self):
        assert fit_lines(["x" * 100], budget=5) == ["x" * 100]


class TestFormatting:
    def test_usage_summary_text(self):
        summary = UsageSummary(
            conversations=3,
            questions=8,
            followups=5,
            users=2,
            api_key_conversations=1,
            buckets=[
                UsageBucket(datetime(2026, 9, 1), 2, 5, 2),
                UsageBucket(datetime(2026, 9, 3), 1, 3, 1),
            ],
        )

        text = _usage_summary_text(summary, _window(), "day", "assistant 'Bygg'")

        assert text.startswith("Usage for assistant 'Bygg', 2026-09-01T00:00+02:00")
        assert "- Questions: 8 (follow-ups: 5, 62.5%)" in text
        assert "API-key conversations: 1" in text
        assert "2026-09-01 | conversations=2 | questions=5 | users=2" in text
        assert "2026-09-03 | conversations=1 | questions=3 | users=1" in text

    def test_usage_summary_text_month_buckets(self):
        summary = UsageSummary(
            1, 1, 0, 1, 0, [UsageBucket(datetime(2026, 9, 1), 1, 1, 1)]
        )

        text = _usage_summary_text(summary, _window(), "month", "assistant 'A'")

        assert "2026-09 | conversations=1" in text

    def test_usage_summary_empty(self):
        summary = UsageSummary(0, 0, 0, 0, 0, [])

        assert _usage_summary_text(
            summary, _window(), "day", "assistant 'A'"
        ).startswith("No questions for assistant 'A'")

    def test_list_questions_lines_use_local_time_and_continue_by_offset(self):
        session_id = uuid4()
        rows = [
            QuestionRow(
                created_at=datetime(2026, 9, 7, 12, 3, tzinfo=timezone.utc),
                session_id=session_id,
                question="Hur   ansöker jag\nom bygglov?",
                is_followup=False,
            ),
            QuestionRow(
                created_at=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
                session_id=uuid4(),
                question="x" * 400,
                is_followup=False,
            ),
        ]

        text = _list_questions_text(
            rows,
            total=5,
            offset=2,
            include_followups=False,
            window=_window(),
            label="assistant 'A'",
            page_cap=10_000,
        )

        assert text.startswith("Questions 3-4 of 5 for assistant 'A'")
        assert "opening questions only" in text
        assert (
            f"2026-09-07 14:03 | session_id={session_id} | Hur ansöker jag om bygglov?"
            in text
        )
        assert "x" * 300 + "…" in text
        assert "offset=4 for the next part" in text

    def test_list_questions_page_cap_shortens_the_page(self):
        rows = [
            QuestionRow(
                datetime(2026, 9, 7, tzinfo=timezone.utc), uuid4(), "q" * 200, False
            )
            for _ in range(5)
        ]

        text = _list_questions_text(
            rows,
            total=5,
            offset=0,
            include_followups=True,
            window=_window(),
            label="assistant 'A'",
            page_cap=300,
        )

        assert text.startswith("Questions 1-1 of 5")
        assert "offset=1 for the next part" in text

    def test_list_questions_past_the_end_and_empty(self):
        common = dict(
            include_followups=False,
            window=_window(),
            label="assistant 'A'",
            page_cap=1000,
        )

        assert "past the end" in _list_questions_text([], total=3, offset=9, **common)
        assert "No questions" in _list_questions_text([], total=0, offset=0, **common)

    def test_top_questions_text(self):
        session_id = uuid4()
        rows = [
            TopQuestionRow("Hur ansöker jag om bygglov?", 6, 5, [session_id]),
            TopQuestionRow("Vad kostar det?", 1, 1, [uuid4()]),
        ]

        text = _top_questions_text(
            rows,
            total=20,
            include_followups=False,
            window=_window(),
            label="group chat 'Team'",
            page_cap=10_000,
        )

        assert text.startswith("Top 2 exact-text question groups of 20 questions")
        assert (
            f'1. 6x (30.0%, 5 conversations) "Hur ansöker jag om bygglov?" sessions: {session_id}'
            in text
        )
        assert "2. 1x (5.0%, 1 conversations)" in text
        assert 'A row with count 1 is not "most common"' in text
        assert "merge near-duplicates yourself" in text


def _patch_tool_context(monkeypatch, *, repo):
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())

    @asynccontextmanager
    async def fake_context(_ctx):
        yield SimpleNamespace(
            container=SimpleNamespace(insights_repo=lambda: repo),
            user=SimpleNamespace(),
            scope=scope,
            target_label="assistant 'Bygg'",
        )

    monkeypatch.setattr(insights, "insight_tool_context", fake_context)
    return scope


class TestTools:
    @pytest.mark.asyncio
    async def test_usage_summary_passes_scope_window_and_granularity(self, monkeypatch):
        calls = []

        async def count_usage(scope, window, granularity):
            calls.append((scope, window, granularity))
            return UsageSummary(
                1, 2, 1, 1, 0, [UsageBucket(datetime(2026, 9, 1), 1, 2, 1)]
            )

        scope = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(count_usage=count_usage)
        )

        text = await usage_summary(
            ctx=None, start=START, end=END, timezone=STOCKHOLM, granularity="week"
        )

        assert calls == [(scope, _window(), "week")]
        assert "Usage for assistant 'Bygg'" in text
        assert "Per week" in text

    @pytest.mark.asyncio
    async def test_list_questions_clamps_paging_arguments(self, monkeypatch):
        calls = []

        async def list_rows(scope, window, *, include_followups, offset, limit):
            calls.append((include_followups, offset, limit))
            return [], 0

        _patch_tool_context(monkeypatch, repo=SimpleNamespace(list_questions=list_rows))

        await list_questions(
            ctx=None,
            start=START,
            end=END,
            include_followups=True,
            offset=-5,
            limit=9999,
        )

        assert calls == [(True, 0, insights.LIST_LIMIT_CEILING)]

    @pytest.mark.asyncio
    async def test_top_questions_clamps_n_and_reports_groups(self, monkeypatch):
        calls = []
        session_id = uuid4()

        async def top(scope, window, *, n, include_followups):
            calls.append((n, include_followups))
            return [TopQuestionRow("Öppettider?", 4, 4, [session_id])], 10

        _patch_tool_context(monkeypatch, repo=SimpleNamespace(top_questions=top))

        text = await top_questions(ctx=None, start=START, end=END, n=500)

        assert calls == [(insights.TOP_N_CEILING, False)]
        assert (
            f'1. 4x (40.0%, 4 conversations) "Öppettider?" sessions: {session_id}'
            in text
        )


class TestInsightToolContext:
    @pytest.mark.asyncio
    async def test_rechecks_access_and_yields_scope(self, monkeypatch):
        target_id = uuid4()
        tenant_id = uuid4()
        checks = []

        async def assert_insight_access(**kwargs):
            checks.append(kwargs)
            return SimpleNamespace(name="Bygg"), SimpleNamespace()

        container = SimpleNamespace(
            analysis_service=lambda: SimpleNamespace(
                assert_insight_access=assert_insight_access
            )
        )

        @asynccontextmanager
        async def fake_bootstrap(_token):
            yield container, SimpleNamespace(tenant_id=tenant_id)

        monkeypatch.setattr(insights, "bearer_from_ctx", lambda _ctx: "tok")
        monkeypatch.setattr(
            insights, "insight_target_from_token", lambda _t: ("group_chat", target_id)
        )
        monkeypatch.setattr(insights, "bootstrap_tool_container", fake_bootstrap)

        async with insights.insight_tool_context(None) as tool:
            assert tool.scope == InsightScope("group_chat", target_id, tenant_id)
            assert tool.target_label == "group chat 'Bygg'"
        assert checks == [{"group_chat_id": target_id}]

    @pytest.mark.asyncio
    async def test_access_failure_propagates_before_any_tool_work(self, monkeypatch):
        async def assert_insight_access(**kwargs):
            raise PermissionError("no insights")

        container = SimpleNamespace(
            analysis_service=lambda: SimpleNamespace(
                assert_insight_access=assert_insight_access
            )
        )

        @asynccontextmanager
        async def fake_bootstrap(_token):
            yield container, SimpleNamespace(tenant_id=uuid4())

        monkeypatch.setattr(insights, "bearer_from_ctx", lambda _ctx: "tok")
        monkeypatch.setattr(
            insights, "insight_target_from_token", lambda _t: ("assistant", uuid4())
        )
        monkeypatch.setattr(insights, "bootstrap_tool_container", fake_bootstrap)

        with pytest.raises(PermissionError):
            async with insights.insight_tool_context(None):
                pass


class TestBuildInsightsMcpServer:
    @pytest.mark.asyncio
    async def test_tool_entities_mirror_live_tools_with_target_suffix(self):
        server = await build_insights_mcp_server(
            token="tok", tenant_id=uuid4(), target_label="assistant 'Bygg'"
        )

        live_tools = await mcp.list_tools()
        assert [t.name for t in server.tools] == [t.name for t in live_tools]
        assert {"usage_summary", "list_questions", "top_questions"} == {
            t.name for t in server.tools
        }
        for entity, live in zip(server.tools, live_tools):
            assert entity.description.startswith(live.description)
            assert entity.description.endswith("\n\nTarget: assistant 'Bygg'.")
            assert entity.input_schema == live.inputSchema

    @pytest.mark.asyncio
    async def test_server_is_bearer_authenticated_loopback(self):
        server = await build_insights_mcp_server(
            token="tok", tenant_id=uuid4(), target_label="group chat 'Team'"
        )

        assert server.name == INSIGHTS_SERVER_NAME
        assert server.http_auth_type == "bearer"
        assert server.http_auth_config_schema == {"token": "tok"}
        assert server.http_url.endswith("/internal-mcp/insights/mcp")
        assert "group chat 'Team'" in server.description

    def test_server_is_mounted(self):
        assert "/internal-mcp/insights" in dict(internal_mcp_mounts())

    def test_target_label(self):
        assert target_label("assistant", "Bygg") == "assistant 'Bygg'"
        assert target_label("group_chat", "Team") == "group chat 'Team'"
