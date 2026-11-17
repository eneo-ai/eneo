"""Unit tests for the loopback insights MCP server.

Covers scope resolution from the token, window validation, the self-capped
page formatting each tool emits and the questions each page names as its
sources, the tools themselves against a fake repository (each text tool
registers exactly what it prints before the text leaves it), and the
ephemeral-server builder.
"""

from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import pytest

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    KnowledgeCitations,
    KnowledgeSourceRow,
    NoKnowledgeRow,
    QuestionRow,
    RatingRow,
    RephrasingRow,
    SearchHit,
    ToolUseRow,
    TopQuestionRow,
    Transcript,
    TranscriptTurn,
    UnansweredRow,
    UsageBucket,
    UsageSummary,
)
from eneo.data_retention.derivations import DerivationRegistrationError
from eneo.internal_mcp import insights
from eneo.internal_mcp.insights import (
    CONVERSATION_NOT_FOUND_MESSAGE,
    INSIGHTS_SERVER_NAME,
    MAX_WINDOW_DAYS,
    SOURCES_NOT_RECORDED_MESSAGE,
    _bucket_count,
    _list_questions_text,
    _parse_window,
    _search_text,
    _top_questions_text,
    _transcript_text,
    _usage_summary_text,
    build_insights_mcp_server,
    find_gaps,
    knowledge_use,
    list_questions,
    list_ratings,
    mcp,
    read_conversation,
    search_questions,
    target_label,
    tool_use,
    top_questions,
    usage_summary,
)
from eneo.internal_mcp.registry import internal_mcp_mounts

STOCKHOLM = "Europe/Stockholm"
START = "2026-09-01T00:00:00+02:00"
END = "2026-09-08T00:00:00+02:00"
CTX: Any = None


def _window(start: str = START, end: str = END, tz: str = STOCKHOLM) -> InsightWindow:
    return _parse_window(start, end, tz)


def _summary(
    *buckets: UsageBucket,
    conversations: int = 1,
    questions: int = 1,
    followups: int = 0,
    users: int = 1,
    api_key_conversations: int = 0,
    widget_conversations: int = 0,
) -> UsageSummary:
    return UsageSummary(
        conversations=conversations,
        questions=questions,
        followups=followups,
        users=users,
        api_key_conversations=api_key_conversations,
        widget_conversations=widget_conversations,
        buckets=list(buckets),
    )


def _question(text: str, **overrides: Any) -> QuestionRow:
    fields: dict[str, Any] = dict(
        question_id=uuid4(),
        created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        session_id=uuid4(),
        question=text,
        is_followup=False,
    )
    fields.update(overrides)
    return QuestionRow(**fields)


def _turn(question: str, answer: str, **overrides: Any) -> TranscriptTurn:
    fields: dict[str, Any] = dict(
        question_id=uuid4(),
        created_at=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
        question=question,
        answer=answer,
        cited_passages=0,
        best_score=None,
        tool_names=[],
    )
    fields.update(overrides)
    return TranscriptTurn(**fields)


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
    def test_rejections(self, start: str, end: str, tz: str, fragment: str):
        with pytest.raises(ValueError, match=fragment):
            _parse_window(start, end, tz)


class TestBucketCount:
    def test_days_weeks_months(self):
        window = _window("2026-01-01T00:00:00+01:00", "2026-12-31T00:00:00+01:00")

        assert _bucket_count(window, "day") == 365
        assert _bucket_count(window, "week") == 53
        assert _bucket_count(window, "month") == 12

    async def test_usage_summary_refuses_too_many_buckets_before_querying(self):
        text = await usage_summary(
            ctx=CTX,
            start="2026-01-01T00:00:00+01:00",
            end="2026-12-31T00:00:00+01:00",
            timezone=STOCKHOLM,
            granularity="day",
        )

        assert "coarser granularity" in text

    async def test_tools_return_window_errors_as_text(self):
        text = await list_questions(ctx=CTX, start=END, end=START)

        assert "end must be after start" in text


class TestFormatting:
    def test_usage_summary_text(self):
        summary = _summary(
            UsageBucket(datetime(2026, 9, 1), 2, 5, 2),
            UsageBucket(datetime(2026, 9, 3), 1, 3, 1),
            conversations=3,
            questions=8,
            followups=5,
            users=2,
            api_key_conversations=1,
            widget_conversations=2,
        )

        text = _usage_summary_text(summary, _window(), "day", "assistant 'Bygg'")

        assert text.startswith("Usage for assistant 'Bygg', 2026-09-01T00:00+02:00")
        assert "- Questions: 8 (follow-ups: 5, 62.5%)" in text
        assert "API-key conversations: 1, widget conversations: 2" in text
        assert "2026-09-01 | conversations=2 | questions=5 | users=2" in text
        assert "2026-09-03 | conversations=1 | questions=3 | users=1" in text

    def test_usage_summary_text_month_buckets(self):
        summary = _summary(UsageBucket(datetime(2026, 9, 1), 1, 1, 1))

        text = _usage_summary_text(summary, _window(), "month", "assistant 'A'")

        assert "2026-09 | conversations=1" in text

    def test_usage_summary_empty(self):
        summary = _summary(conversations=0, questions=0, users=0)

        assert _usage_summary_text(
            summary, _window(), "day", "assistant 'A'"
        ).startswith("No questions for assistant 'A'")

    def test_list_questions_lines_use_local_time_and_continue_by_offset(self):
        session_id = uuid4()
        rows = [
            _question(
                "Hur   ansöker jag\nom bygglov?",
                created_at=datetime(2026, 9, 7, 12, 3, tzinfo=timezone.utc),
                session_id=session_id,
            ),
            _question(
                "x" * 400, created_at=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
            ),
        ]

        page = _list_questions_text(
            rows,
            total=5,
            offset=2,
            include_followups=False,
            window=_window(),
            label="assistant 'A'",
            page_cap=10_000,
        )

        assert page.text.startswith("Questions 3-4 of 5 for assistant 'A'")
        assert "opening questions only" in page.text
        assert (
            f"2026-09-07 14:03 | session_id={session_id} | Hur ansöker jag om bygglov?"
            in page.text
        )
        assert "x" * 300 + "…" in page.text
        assert "offset=4 for the next part" in page.text
        assert page.question_ids == [row.question_id for row in rows]

    def test_list_questions_page_cap_shortens_the_page_and_its_sources(self):
        rows = [_question("q" * 200) for _ in range(5)]

        page = _list_questions_text(
            rows,
            total=5,
            offset=0,
            include_followups=True,
            window=_window(),
            label="assistant 'A'",
            page_cap=300,
        )

        assert page.text.startswith("Questions 1-1 of 5")
        assert "offset=1 for the next part" in page.text
        # Only the question the page prints is its source.
        assert page.question_ids == [rows[0].question_id]

    def test_list_questions_past_the_end_and_empty_name_no_sources(self):
        common: dict[str, Any] = dict(
            include_followups=False,
            window=_window(),
            label="assistant 'A'",
            page_cap=1000,
        )

        past = _list_questions_text([], total=3, offset=9, **common)
        empty = _list_questions_text([], total=0, offset=0, **common)

        assert "past the end" in past.text and past.question_ids == []
        assert "No questions" in empty.text and empty.question_ids == []

    def test_top_questions_text_names_every_question_of_a_printed_group(self):
        session_id = uuid4()
        group = [uuid4(), uuid4()]
        rows = [
            TopQuestionRow("Hur ansöker jag om bygglov?", 6, 5, [session_id], group),
            TopQuestionRow("Vad kostar det?", 1, 1, [uuid4()], [uuid4()]),
        ]

        page = _top_questions_text(
            rows,
            total=20,
            include_followups=False,
            window=_window(),
            label="group chat 'Team'",
            page_cap=10_000,
        )

        assert page.text.startswith("Top 2 exact-text question groups of 20 questions")
        assert (
            f'1. 6x (30.0%, 5 conversations) "Hur ansöker jag om bygglov?" sessions: {session_id}'
            in page.text
        )
        assert "2. 1x (5.0%, 1 conversations)" in page.text
        assert 'A row with count 1 is not "most common"' in page.text
        assert "merge near-duplicates yourself" in page.text
        assert page.question_ids == [*group, *rows[1].question_ids]


def _patch_tool_context(
    monkeypatch: pytest.MonkeyPatch, *, repo: Any, has_knowledge: bool = True
) -> tuple[InsightScope, list[list[UUID]]]:
    """Fake the tool context and record the sources each call registers.

    The fake registration also checks that it is made for the conversation
    the tools answer in, and only after the tool's own transaction closed.
    """
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())
    session_id = uuid4()
    registered: list[list[UUID]] = []
    open_contexts: list[int] = []

    @asynccontextmanager
    async def fake_context(_ctx: Any):
        open_contexts.append(1)
        try:
            yield SimpleNamespace(
                container=SimpleNamespace(insights_repo=lambda: repo),
                user=SimpleNamespace(),
                scope=scope,
                target_label="assistant 'Bygg'",
                session_id=session_id,
                has_knowledge=has_knowledge,
            )
        finally:
            open_contexts.pop()

    async def register(
        *, copy_session_id: UUID, source_question_ids: Sequence[UUID]
    ) -> None:
        assert copy_session_id == session_id
        assert open_contexts == [], "registered inside the tool's transaction"
        registered.append(list(source_question_ids))

    monkeypatch.setattr(insights, "insight_tool_context", fake_context)
    monkeypatch.setattr(insights, "register_derivations", register)
    return scope, registered


class TestTools:
    async def test_usage_summary_passes_scope_window_and_granularity(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[tuple[Any, ...]] = []

        async def count_usage(scope: Any, window: Any, granularity: Any):
            calls.append((scope, window, granularity))
            return _summary(
                UsageBucket(datetime(2026, 9, 1), 1, 2, 1), questions=2, followups=1
            )

        scope, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(count_usage=count_usage)
        )

        text = await usage_summary(
            ctx=CTX, start=START, end=END, timezone=STOCKHOLM, granularity="week"
        )

        assert calls == [(scope, _window(), "week")]
        assert "Usage for assistant 'Bygg'" in text
        assert "Per week" in text
        # Counts carry no text from the conversations: nothing to register.
        assert registered == []

    async def test_list_questions_clamps_paging_and_registers_what_it_prints(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[tuple[Any, ...]] = []
        row = _question("Öppettider?")

        async def list_rows(
            scope: Any, window: Any, *, include_followups: bool, offset: int, limit: int
        ):
            calls.append((include_followups, offset, limit))
            return [row], 1

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(list_questions=list_rows)
        )

        text = await list_questions(
            ctx=CTX,
            start=START,
            end=END,
            include_followups=True,
            offset=-5,
            limit=9999,
        )

        assert calls == [(True, 0, insights.LIST_LIMIT_CEILING)]
        assert "Öppettider?" in text
        assert registered == [[row.question_id]]

    async def test_top_questions_clamps_n_and_reports_groups(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[tuple[Any, ...]] = []
        session_id = uuid4()
        group = [uuid4(), uuid4()]

        async def top(scope: Any, window: Any, *, n: int, include_followups: bool):
            calls.append((n, include_followups))
            return [TopQuestionRow("Öppettider?", 4, 4, [session_id], group)], 10

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(top_questions=top)
        )

        text = await top_questions(ctx=CTX, start=START, end=END, n=500)

        assert calls == [(insights.TOP_N_CEILING, False)]
        assert (
            f'1. 4x (40.0%, 4 conversations) "Öppettider?" sessions: {session_id}'
            in text
        )
        assert registered == [group]


class TestInsightToolContext:
    async def test_rechecks_access_and_yields_scope_and_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        target_id = uuid4()
        tenant_id = uuid4()
        session_id = uuid4()
        checks: list[dict[str, Any]] = []

        async def assert_insight_access(**kwargs: Any):
            checks.append(kwargs)
            return SimpleNamespace(name="Bygg", assistants=[]), SimpleNamespace()

        container = SimpleNamespace(
            analysis_service=lambda: SimpleNamespace(
                assert_insight_access=assert_insight_access
            )
        )

        @asynccontextmanager
        async def fake_container(_token: str):
            yield container, SimpleNamespace(tenant_id=tenant_id)

        monkeypatch.setattr(insights, "bearer_from_ctx", lambda _ctx: "tok")
        monkeypatch.setattr(
            insights, "insight_target_from_token", lambda _t: ("group_chat", target_id)
        )
        monkeypatch.setattr(
            insights, "insight_session_from_token", lambda _t: session_id
        )
        monkeypatch.setattr(insights, "account_tool_container", fake_container)

        async with insights.insight_tool_context(CTX) as tool:
            assert tool.scope == InsightScope("group_chat", target_id, tenant_id)
            assert tool.target_label == "group chat 'Bygg'"
            assert tool.session_id == session_id
            assert tool.has_knowledge is False
        assert checks == [{"group_chat_id": target_id}]

    async def test_access_failure_propagates_before_any_tool_work(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        async def assert_insight_access(**kwargs: Any):
            raise PermissionError("no insights")

        container = SimpleNamespace(
            analysis_service=lambda: SimpleNamespace(
                assert_insight_access=assert_insight_access
            )
        )

        @asynccontextmanager
        async def fake_container(_token: str):
            yield container, SimpleNamespace(tenant_id=uuid4())

        monkeypatch.setattr(insights, "bearer_from_ctx", lambda _ctx: "tok")
        monkeypatch.setattr(
            insights, "insight_target_from_token", lambda _t: ("assistant", uuid4())
        )
        monkeypatch.setattr(insights, "insight_session_from_token", lambda _t: uuid4())
        monkeypatch.setattr(insights, "account_tool_container", fake_container)

        with pytest.raises(PermissionError):
            async with insights.insight_tool_context(CTX):
                pass


class TestBuildInsightsMcpServer:
    async def test_tool_entities_mirror_live_tools_with_target_suffix(self):
        server = await build_insights_mcp_server(
            token="tok", tenant_id=uuid4(), target_label="assistant 'Bygg'"
        )

        live_tools = await mcp.list_tools()
        assert [t.name for t in server.tools] == [t.name for t in live_tools]
        assert {
            "usage_summary",
            "list_questions",
            "top_questions",
            "search_questions",
            "read_conversation",
            "find_gaps",
            "list_ratings",
            "knowledge_use",
            "tool_use",
        } == {t.name for t in server.tools}
        for entity, live in zip(server.tools, live_tools):
            assert entity.description is not None and live.description is not None
            assert entity.description.startswith(live.description)
            assert entity.description.endswith("\n\nTarget: assistant 'Bygg'.")
            assert entity.input_schema == live.inputSchema

    async def test_tools_only_read_and_return_plain_text(self):
        """No tool is asked about before it runs, and none returns structured
        content: a result reaches the browser only through the tool-result
        endpoint, never in the stream or the saved conversation."""
        for tool in await mcp.list_tools():
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.outputSchema is None

    async def test_server_is_bearer_authenticated_loopback(self):
        server = await build_insights_mcp_server(
            token="tok", tenant_id=uuid4(), target_label="group chat 'Team'"
        )

        assert server.name == INSIGHTS_SERVER_NAME
        assert server.is_internal is True
        assert server.http_auth_type == "bearer"
        assert server.http_auth_config_schema == {"token": "tok"}
        assert server.http_url.endswith("/internal-mcp/insights/mcp")
        assert server.description is not None
        assert "group chat 'Team'" in server.description

    def test_server_is_mounted(self):
        assert "/internal-mcp/insights" in dict(internal_mcp_mounts())

    def test_target_label(self):
        assert target_label("assistant", "Bygg") == "assistant 'Bygg'"
        assert target_label("group_chat", "Team") == "group chat 'Team'"


class TestSearchAndTranscriptFormatting:
    def test_search_text_marks_exact_and_similar_hits_and_answers(self):
        session_id = uuid4()
        hits = [
            SearchHit(
                uuid4(),
                datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
                session_id,
                "Var parkerar jag?",
                "Vid torget.",
                False,
                True,
            ),
            SearchHit(
                uuid4(),
                datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
                uuid4(),
                "Parkering centrum",
                "x",
                True,
                False,
            ),
        ]

        page = _search_text(
            hits,
            query="parkera",
            total=2,
            offset=0,
            include_answers=True,
            window=_window(),
            label="assistant 'A'",
            page_cap=10_000,
        )

        assert page.text.startswith("Questions 1-2 of 2 matching 'parkera'")
        assert (
            f"session_id={session_id} | exact | Q: Var parkerar jag? | A: Vid torget."
            in page.text
        )
        assert "| similar | Q: Parkering centrum" in page.text
        assert page.question_ids == [hit.question_id for hit in hits]

    def test_search_text_empty_suggests_shorter_query(self):
        page = _search_text(
            [],
            query="hela meningen här",
            total=0,
            offset=0,
            include_answers=False,
            window=_window(),
            label="assistant 'A'",
            page_cap=100,
        )

        assert "No questions matching" in page.text and "shorter" in page.text
        assert page.question_ids == []

    def test_transcript_pages_by_characters_and_names_the_turns_it_shows(self):
        first = _turn(
            "Hur ansöker jag om bygglov?",
            "Via e-tjänsten.",
            cited_passages=2,
            best_score=0.81,
            tool_names=["knowledge.search_knowledge"],
        )
        second = _turn(
            "Vad kostar det?",
            "",
            created_at=datetime(2026, 9, 7, 8, 3, tzinfo=timezone.utc),
        )
        transcript = Transcript(
            session_id=uuid4(),
            started_at=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            turns=[first, second],
        )

        full = _transcript_text(
            transcript, offset=0, timezone=STOCKHOLM, page_cap=10_000
        )
        assert "2 turns" in full.text
        assert "### Turn 1 (10:00)" in full.text
        assert "User: Hur ansöker jag om bygglov?" in full.text
        assert (
            "[cited passages: 2; best score: 0.81; tools: knowledge.search_knowledge]"
            in full.text
        )
        assert "Assistant: (no answer)" in full.text
        assert full.question_ids == [first.question_id, second.question_id]

        # The header alone shows no turn.
        header = _transcript_text(transcript, offset=0, timezone=STOCKHOLM, page_cap=40)
        assert "read_conversation again with offset=40" in header.text
        assert header.question_ids == []

        # A page from inside the second turn names that turn only.
        offset = full.text.index("### Turn 2")
        tail = _transcript_text(
            transcript, offset=offset, timezone=STOCKHOLM, page_cap=10_000
        )
        assert tail.question_ids == [second.question_id]

        past = _transcript_text(
            transcript, offset=10_000, timezone=STOCKHOLM, page_cap=80
        )
        assert "past the end" in past.text and past.question_ids == []


class TestSearchConversationAndGapTools:
    async def test_search_questions_rejects_empty_query_without_a_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        called: list[int] = []

        async def search(*args: Any, **kwargs: Any):
            called.append(1)
            return [], 0

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(search_questions=search)
        )

        text = await search_questions(ctx=CTX, query="   ", start=START, end=END)

        assert "must not be empty" in text and called == []
        assert registered == []

    async def test_search_questions_passes_query_and_paging(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[tuple[Any, ...]] = []

        async def search(
            scope: Any, window: Any, *, query: str, offset: int, limit: int
        ):
            calls.append((query, offset, limit))
            return [], 0

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(search_questions=search)
        )

        await search_questions(
            ctx=CTX, query=" bygglov ", start=START, end=END, offset=-1, limit=999
        )

        assert calls == [("bygglov", 0, insights.LIST_LIMIT_CEILING)]
        assert registered == [[]]

    async def test_read_conversation_not_found_parity(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        async def transcript(scope: Any, session_id: Any):
            return None

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(get_transcript=transcript)
        )

        missing = await read_conversation(ctx=CTX, session_id=str(uuid4()))
        malformed = await read_conversation(ctx=CTX, session_id="not-a-uuid")

        assert missing == CONVERSATION_NOT_FOUND_MESSAGE
        assert malformed == CONVERSATION_NOT_FOUND_MESSAGE
        assert registered == []

    async def test_read_conversation_registers_the_turns_it_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        turn = _turn("Hur ansöker jag om bygglov?", "Via e-tjänsten.")
        session_id = uuid4()

        async def transcript(scope: Any, wanted: Any):
            return Transcript(session_id, turn.created_at, [turn])

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(get_transcript=transcript)
        )

        text = await read_conversation(ctx=CTX, session_id=str(session_id))

        assert "User: Hur ansöker jag om bygglov?" in text
        assert registered == [[turn.question_id]]

    async def test_find_gaps_all_pages_every_signal_and_registers_them(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        session_id = uuid4()
        at = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
        unanswered_row = UnansweredRow(
            uuid4(), at, session_id, "Vad kostar det?", "hittar tyvärr inte", "user", -1
        )
        no_knowledge_row = NoKnowledgeRow(
            uuid4(), at, session_id, "Q", "uncited", None, "widget", None
        )
        rephrasing_row = RephrasingRow(
            session_id,
            at,
            ["a?", "a igen?", "a???"],
            2,
            [uuid4(), uuid4(), uuid4()],
            "user",
        )

        async def unanswered(scope: Any, window: Any, *, offset: int, limit: int):
            return [unanswered_row], 1

        async def no_knowledge(scope: Any, window: Any, *, offset: int, limit: int):
            return [no_knowledge_row], 1, 0.7

        async def rephrasing(scope: Any, window: Any, *, offset: int, limit: int):
            return [rephrasing_row], 1

        repo = SimpleNamespace(
            find_unanswered=unanswered,
            find_no_knowledge=no_knowledge,
            find_rephrasing=rephrasing,
        )
        _, registered = _patch_tool_context(monkeypatch, repo=repo)

        text = await find_gaps(ctx=CTX, start=START, end=END, signal="all")

        assert "Unanswered (1 turns admit not knowing)" in text
        assert 'admits: "hittar tyvärr inte"' in text
        assert "No knowledge used (1 turns; window median best score 0.70)" in text
        assert "| answer cited no knowledge" in text
        assert "Rephrasing (1 conversations)" in text
        assert '"a?" -> "a igen?" -> "a???"' in text
        assert "heuristic candidates" in text
        assert registered == [
            [
                unanswered_row.question_id,
                no_knowledge_row.question_id,
                *rephrasing_row.question_ids,
            ]
        ]

    async def test_find_gaps_skips_no_knowledge_without_knowledge(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        called: list[int] = []

        async def no_knowledge(scope: Any, window: Any, *, offset: int, limit: int):
            called.append(1)
            return [], 0, None

        _patch_tool_context(
            monkeypatch,
            repo=SimpleNamespace(find_no_knowledge=no_knowledge),
            has_knowledge=False,
        )

        text = await find_gaps(ctx=CTX, start=START, end=END, signal="no_knowledge")

        assert "No-knowledge signal skipped" in text and called == []

    async def test_find_gaps_single_signal_reports_none(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        async def unanswered(scope: Any, window: Any, *, offset: int, limit: int):
            return [], 0

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(find_unanswered=unanswered)
        )

        text = await find_gaps(ctx=CTX, start=START, end=END, signal="unanswered")

        assert "(none)" in text
        assert registered == [[]]


def _rating_row(question: str, quoted: UUID, **overrides: Any) -> RatingRow:
    fields: dict[str, Any] = dict(
        kind="answer",
        value=-1,
        comment="Saknar avgiften",
        question=question,
        question_id=quoted,
        session_id=uuid4(),
        source="user",
        rated_at=datetime(2026, 9, 7, 10, 6, tzinfo=timezone.utc),
        key=quoted,
        quoted_question_id=quoted,
    )
    fields.update(overrides)
    return RatingRow(**fields)


class TestRatingsKnowledgeAndToolUse:
    async def test_list_ratings_filters_pages_and_registers_the_quoted_questions(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[dict[str, Any]] = []
        answer = _rating_row("Vad kostar det?", uuid4())
        first_question = uuid4()
        vote = _rating_row(
            "När öppnar simhallen?",
            first_question,
            kind="conversation",
            question_id=None,
            key=uuid4(),
            comment=None,
        )

        async def ratings(scope: Any, window: Any, **kwargs: Any):
            calls.append(kwargs)
            return [answer, vote], 2, False

        _, registered = _patch_tool_context(
            monkeypatch, repo=SimpleNamespace(list_ratings=ratings)
        )

        text = await list_ratings(
            ctx=CTX,
            start=START,
            end=END,
            rating="bad",
            comments_only=True,
            offset=-3,
            limit=9999,
            timezone=STOCKHOLM,
        )

        assert calls == [
            dict(
                source=None,
                value=-1,
                has_comment=True,
                limit=insights.LIST_LIMIT_CEILING,
                after=None,
                offset=0,
            )
        ]
        assert "Ratings 1-2 of 2 (bad ratings, with a comment)" in text
        assert (
            "12:06 | session_id="
            f'{answer.session_id} | answer rated bad | Q: Vad kostar det? | comment: "Saknar avgiften"'
            in text
        )
        assert (
            "conversation rated bad | first Q: När öppnar simhallen? | no comment"
            in text
        )
        # A conversation rating quotes the conversation's first question.
        assert registered == [[answer.question_id, first_question]]

    async def test_knowledge_and_tool_use_return_counts_and_register_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        bygglov = KnowledgeSourceRow("collection", uuid4(), "Bygglov", 6, True)
        old_site = KnowledgeSourceRow("website", uuid4(), "gamla.se", 2, False)
        unused = KnowledgeSourceRow(
            "integration_knowledge", uuid4(), "Intranät", 0, True
        )

        async def citations(scope: Any, window: Any, *, source: Any):
            return KnowledgeCitations(20, 8, [bygglov, old_site], [unused])

        async def tools(scope: Any, window: Any, *, source: Any):
            return [
                ToolUseRow("web_search", None, None, None, 40, 2, 0),
                ToolUseRow(None, "Grounding", "get_chat_grounding", "Grund", 10, 6, 1),
            ]

        _, registered = _patch_tool_context(
            monkeypatch,
            repo=SimpleNamespace(knowledge_citations=citations, tool_use=tools),
        )

        knowledge = await knowledge_use(ctx=CTX, start=START, end=END)
        used = await tool_use(ctx=CTX, start=START, end=END)
        past = await tool_use(ctx=CTX, start=START, end=END, offset=5)

        assert "20 answers, of which 8 (40.0%) cited a passage" in knowledge
        assert (
            "cited | collection 'Bygglov' | 6 answers (75.0% of citing answers)"
            in knowledge
        )
        assert (
            "website 'gamla.se' | 2 answers (25.0% of citing answers) | no longer attached"
            in knowledge
        )
        assert "never cited | integration knowledge 'Intranät' | attached" in knowledge
        assert "capability web_search | 40 calls | 2 failed (5.0%) | 0 denied" in used
        assert (
            "server 'Grounding' tool 'get_chat_grounding' (\"Grund\") | 10 calls | "
            "6 failed (60.0%) | 1 denied" in used
        )
        assert "past the end (2 tools)" in past
        # Counts and configured names carry no conversation text.
        assert registered == []


AT = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)


class _PrintCase(NamedTuple):
    """A text tool over a fake repository whose rows each carry a marker."""

    repo: Any
    # Each marker and the questions whose text carries it.
    sources: list[tuple[str, list[UUID]]]
    call: Callable[[], Awaitable[str]]
    # Small enough that the page shows only part of what was read.
    page_cap: int


def _markers(count: int, start: int = 0) -> list[tuple[str, list[UUID]]]:
    # The trailing x keeps one marker from being a prefix of another.
    return [(f"mark{start + index}x", [uuid4()]) for index in range(count)]


def _list_case() -> _PrintCase:
    sources = _markers(3)
    rows = [_question(f"{m} question", question_id=ids[0]) for m, ids in sources]

    async def list_rows(scope: Any, window: Any, **_: Any):
        return rows, len(rows)

    return _PrintCase(
        SimpleNamespace(list_questions=list_rows),
        sources,
        lambda: list_questions(ctx=CTX, start=START, end=END),
        page_cap=1,
    )


def _top_case() -> _PrintCase:
    sources = [(f"mark{index}x", [uuid4(), uuid4()]) for index in range(3)]
    rows = [TopQuestionRow(f"{m} question", 2, 2, [uuid4()], ids) for m, ids in sources]

    async def top(scope: Any, window: Any, **_: Any):
        return rows, 6

    return _PrintCase(
        SimpleNamespace(top_questions=top),
        sources,
        lambda: top_questions(ctx=CTX, start=START, end=END),
        page_cap=1,
    )


def _search_case() -> _PrintCase:
    sources = _markers(3)
    hits = [
        SearchHit(ids[0], AT, uuid4(), f"{m} question", "an answer", False, True)
        for m, ids in sources
    ]

    async def search(scope: Any, window: Any, **_: Any):
        return hits, len(hits)

    return _PrintCase(
        SimpleNamespace(search_questions=search),
        sources,
        lambda: search_questions(
            ctx=CTX, query="question", start=START, end=END, include_answers=True
        ),
        page_cap=1,
    )


def _transcript_case() -> _PrintCase:
    sources = _markers(3)
    transcript = Transcript(
        uuid4(),
        AT,
        [_turn(f"{m} question", "an answer", question_id=ids[0]) for m, ids in sources],
    )

    async def get_transcript(scope: Any, wanted: Any):
        return transcript

    full = _transcript_text(transcript, offset=0, timezone="UTC", page_cap=100_000)
    # A page that starts and ends inside the second turn's text.
    offset = full.text.index("mark1x")
    return _PrintCase(
        SimpleNamespace(get_transcript=get_transcript),
        sources,
        lambda: read_conversation(
            ctx=CTX, session_id=str(transcript.session_id), offset=offset
        ),
        page_cap=len("mark1x"),
    )


def _ratings_case() -> _PrintCase:
    sources = _markers(3)
    rows = [
        _rating_row(f"{m} question", ids[0], comment=f"{m} comment")
        for m, ids in sources
    ]
    # A conversation rating quotes its conversation's first question.
    rows[1] = rows[1]._replace(kind="conversation", question_id=None)

    async def ratings(scope: Any, window: Any, **_: Any):
        return rows, len(rows), False

    return _PrintCase(
        SimpleNamespace(list_ratings=ratings),
        sources,
        lambda: list_ratings(ctx=CTX, start=START, end=END),
        page_cap=1,
    )


def _gap_case(signal: Any) -> Callable[[], _PrintCase]:
    def build() -> _PrintCase:
        unanswered = _markers(3)
        no_knowledge = _markers(3, start=3)
        rephrasing = [(f"mark{6 + index}x", [uuid4(), uuid4()]) for index in range(3)]

        async def find_unanswered(scope: Any, window: Any, **_: Any):
            rows = [
                UnansweredRow(
                    ids[0], AT, uuid4(), f"{m} question", "vet inte", "user", None
                )
                for m, ids in unanswered
            ]
            return rows, len(rows)

        async def find_no_knowledge(scope: Any, window: Any, **_: Any):
            rows = [
                NoKnowledgeRow(
                    ids[0], AT, uuid4(), f"{m} question", "no_results", None, "user", 1
                )
                for m, ids in no_knowledge
            ]
            return rows, len(rows), None

        async def find_rephrasing(scope: Any, window: Any, **_: Any):
            rows = [
                RephrasingRow(uuid4(), AT, [f"{m} first", f"{m} again"], 1, ids, "user")
                for m, ids in rephrasing
            ]
            return rows, len(rows)

        by_signal = {
            "unanswered": unanswered,
            "no_knowledge": no_knowledge,
            "rephrasing": rephrasing,
        }
        names = list(by_signal) if signal == "all" else [signal]
        return _PrintCase(
            SimpleNamespace(
                find_unanswered=find_unanswered,
                find_no_knowledge=find_no_knowledge,
                find_rephrasing=find_rephrasing,
            ),
            [source for name in names for source in by_signal[name]],
            lambda: find_gaps(ctx=CTX, start=START, end=END, signal=signal),
            page_cap=1,
        )

    return build


_PRINT_CASES = {
    "list_questions": _list_case,
    "top_questions": _top_case,
    "search_questions": _search_case,
    "read_conversation": _transcript_case,
    "list_ratings": _ratings_case,
    "find_gaps unanswered": _gap_case("unanswered"),
    "find_gaps no_knowledge": _gap_case("no_knowledge"),
    "find_gaps rephrasing": _gap_case("rephrasing"),
    "find_gaps all": _gap_case("all"),
}


def _printed(case: _PrintCase, text: str) -> list[UUID]:
    return [qid for marker, ids in case.sources if marker in text for qid in ids]


@pytest.mark.parametrize("build", _PRINT_CASES.values(), ids=_PRINT_CASES.keys())
async def test_each_text_tool_registers_exactly_the_questions_it_prints(
    build: Callable[[], _PrintCase], monkeypatch: pytest.MonkeyPatch
):
    """Mutants: a tool registers what it read rather than what its page
    shows, registers nothing, or registers for another conversation."""
    case = build()
    _, registered = _patch_tool_context(monkeypatch, repo=case.repo)
    monkeypatch.setattr(insights, "default_page_cap", lambda: case.page_cap)

    text = await case.call()

    printed = _printed(case, text)
    read = [qid for _, ids in case.sources for qid in ids]
    assert printed and len(printed) < len(read), "the page should show a part"
    assert registered == [printed]


@pytest.mark.parametrize("build", _PRINT_CASES.values(), ids=_PRINT_CASES.keys())
async def test_a_tool_returns_none_of_its_page_when_its_sources_are_not_recorded(
    build: Callable[[], _PrintCase], monkeypatch: pytest.MonkeyPatch
):
    """Mutant: the text leaves the tool before, or without, its sources
    being recorded."""
    case = build()
    _patch_tool_context(monkeypatch, repo=case.repo)
    monkeypatch.setattr(insights, "default_page_cap", lambda: case.page_cap)

    async def refuse(**_: Any) -> None:
        raise DerivationRegistrationError("The copy session does not exist.")

    monkeypatch.setattr(insights, "register_derivations", refuse)

    text = await case.call()

    assert text == SOURCES_NOT_RECORDED_MESSAGE
    assert _printed(case, text) == []
