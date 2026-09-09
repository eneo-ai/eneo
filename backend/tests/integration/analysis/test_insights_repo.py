"""Insights repository against a real database.

Window on question time, follow-up detection, calendar buckets in the
operator's zone, exact-text grouping, and the hidden-session rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import normalize_question_text

STOCKHOLM = "Europe/Stockholm"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _window(tz: str = STOCKHOLM) -> InsightWindow:
    return InsightWindow(start=utc(2026, 9, 6), end=utc(2026, 9, 8), timezone=tz)


def _scope(seed, key: str = "bygg", kind: str = "assistant") -> InsightScope:
    return InsightScope(kind=kind, target_id=seed[key], tenant_id=seed["tenant_id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_count_usage_totals_and_local_day_buckets(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.insights_repo()

        stockholm = await repo.count_usage(_scope(seed), _window(), "day")
        utc_summary = await repo.count_usage(_scope(seed), _window("UTC"), "day")

    assert stockholm.questions == 4
    assert stockholm.conversations == 3
    assert stockholm.followups == 1
    assert stockholm.users == 1
    assert stockholm.api_key_conversations == 0
    # 22:30 UTC on the 7th is already the 8th in Stockholm.
    assert [
        (b.bucket_start.date().isoformat(), b.questions) for b in stockholm.buckets
    ] == [
        ("2026-09-06", 1),
        ("2026-09-07", 2),
        ("2026-09-08", 1),
    ]
    assert [
        (b.bucket_start.date().isoformat(), b.questions) for b in utc_summary.buckets
    ] == [
        ("2026-09-06", 1),
        ("2026-09-07", 3),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_questions_is_newest_first_and_hides_hidden_sessions(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.insights_repo()

        opening, total = await repo.list_questions(
            _scope(seed), _window(), include_followups=False, offset=0, limit=50
        )
        everything, total_all = await repo.list_questions(
            _scope(seed), _window(), include_followups=True, offset=0, limit=50
        )
        page, _ = await repo.list_questions(
            _scope(seed), _window(), include_followups=True, offset=1, limit=2
        )

    assert total == 3
    assert [row.session_id for row in opening] == [seed["s2"], seed["s1"], seed["s3"]]
    assert all(not row.is_followup for row in opening)

    assert total_all == 4
    assert [row.question for row in everything] == [
        "hur ansöker jag om bygglov",
        "Vad kostar det?",
        "Hur ansöker jag om bygglov?",
        "Öppettider?",
    ]
    assert [row.is_followup for row in everything] == [False, True, False, False]
    assert [row.question for row in page] == [
        "Vad kostar det?",
        "Hur ansöker jag om bygglov?",
    ]

    texts = {row.question for row in everything}
    assert "helper question" not in texts
    assert "insight question" not in texts
    assert "other question" not in texts
    assert "gc question" not in texts


@pytest.mark.asyncio
@pytest.mark.integration
async def test_window_is_on_question_time(db_container, admin_user, seed_insights):
    """A follow-up asked inside the window counts even though its
    conversation started earlier (here: the same day, but before the cut)."""
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.insights_repo()
        window = InsightWindow(
            start=utc(2026, 9, 7, 10, 3), end=utc(2026, 9, 8), timezone="UTC"
        )

        rows, total = await repo.list_questions(
            _scope(seed), window, include_followups=True, offset=0, limit=50
        )

    assert total == 2
    assert [(row.question, row.is_followup) for row in rows] == [
        ("hur ansöker jag om bygglov", False),
        ("Vad kostar det?", True),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_top_questions_merges_exact_text_after_normalisation(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.insights_repo()

        rows, total = await repo.top_questions(
            _scope(seed), _window(), n=10, include_followups=False
        )
        with_followups, total_with = await repo.top_questions(
            _scope(seed), _window(), n=1, include_followups=True
        )

    assert total == 3
    assert [
        (normalize_question_text(r.display_text), r.occurrences, r.conversations)
        for r in rows
    ] == [
        ("hur ansöker jag om bygglov", 2, 2),
        ("öppettider", 1, 1),
    ]
    assert set(rows[0].sample_session_ids) == {seed["s1"], seed["s2"]}

    assert total_with == 4
    assert len(with_followups) == 1
    assert with_followups[0].occurrences == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_group_chat_scope_sees_only_its_own_questions(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.insights_repo()

        rows, total = await repo.list_questions(
            _scope(seed, "group_chat", "group_chat"),
            _window(),
            include_followups=True,
            offset=0,
            limit=50,
        )
        summary = await repo.count_usage(
            _scope(seed, "group_chat", "group_chat"), _window(), "week"
        )

    assert total == 1
    assert rows[0].question == "gc question"
    assert rows[0].session_id == seed["gc_session"]
    assert summary.conversations == 1
