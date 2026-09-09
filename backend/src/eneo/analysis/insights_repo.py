"""Scoped SQL over ``questions`` / ``sessions`` for the insights tools.

Every query is fixed to one :class:`InsightScope` (tenant + analysed
assistant or group chat) and one :class:`InsightWindow`. The window is
applied on *question* time, not session time, so "yesterday" includes
follow-up questions asked yesterday in conversations that started earlier;
this deliberately differs from the Insights tab's statistics counters, which
count sessions by their start time.

Tenant scoping filters ``Questions.tenant_id`` directly and never joins
``Users``: api-key sessions carry no ``user_id`` and an inner join would drop
them (see ``SessionRepository._filter_by_tenant``).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.sessions.hidden_sessions import exclude_hidden_sessions

Granularity = Literal["day", "week", "month"]

__all__ = [
    "Granularity",
    "InsightScope",
    "InsightWindow",
    "InsightsRepository",
    "QuestionRow",
    "TopQuestionRow",
    "UsageBucket",
    "UsageSummary",
    "normalize_question_text",
    "normalized_question_expr",
]


class UsageBucket(NamedTuple):
    bucket_start: datetime
    conversations: int
    questions: int
    users: int


class UsageSummary(NamedTuple):
    conversations: int
    questions: int
    followups: int
    users: int
    api_key_conversations: int
    buckets: list[UsageBucket]


class QuestionRow(NamedTuple):
    created_at: datetime
    session_id: UUID
    question: str
    is_followup: bool


class TopQuestionRow(NamedTuple):
    display_text: str
    occurrences: int
    conversations: int
    sample_session_ids: list[UUID]


_TRAILING_PUNCTUATION = r"[?!.]+$"


def normalize_question_text(text: str) -> str:
    """Python twin of :func:`normalized_question_expr`; the two must agree."""
    collapsed = re.sub(r"\s+", " ", text.strip())
    stripped = re.sub(_TRAILING_PUNCTUATION, "", collapsed).strip()
    return stripped.lower()


def normalized_question_expr(column: Any) -> sa.ColumnElement[str]:
    """Exact-text grouping key: trim, collapse whitespace, drop trailing
    ``?!.``, lower-case."""
    collapsed = sa.func.regexp_replace(sa.func.btrim(column), r"\s+", " ", "g")
    stripped = sa.func.btrim(
        sa.func.regexp_replace(collapsed, _TRAILING_PUNCTUATION, "")
    )
    return sa.func.lower(stripped)


class InsightsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _is_followup_expr() -> sa.ColumnElement[bool]:
        """``True`` when an earlier question exists in the same session.

        A correlated EXISTS rather than a window rank so the follow-up flag
        stays correct when the window cuts a conversation in half.
        """
        earlier = aliased(Questions)
        return sa.exists(
            sa.select(earlier.id).where(
                earlier.session_id == Questions.session_id,
                sa.tuple_(earlier.created_at, earlier.id)
                < sa.tuple_(Questions.created_at, Questions.id),
            )
        )

    def _scoped_questions(
        self, scope: InsightScope, window: InsightWindow
    ) -> sa.Select[Any]:
        stmt = (
            sa.select(
                Questions.id.label("id"),
                Questions.question.label("question"),
                Questions.created_at.label("created_at"),
                Questions.session_id.label("session_id"),
                Sessions.user_id.label("user_id"),
                Sessions.api_key_id.label("api_key_id"),
                self._is_followup_expr().label("is_followup"),
            )
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(Questions.tenant_id == scope.tenant_id)
            .where(Questions.question.isnot(None))
            .where(Questions.created_at >= window.start)
            .where(Questions.created_at < window.end)
        )
        if scope.kind == "assistant":
            stmt = stmt.where(Sessions.assistant_id == scope.target_id)
        else:
            stmt = stmt.where(Sessions.group_chat_id == scope.target_id)
        return exclude_hidden_sessions(stmt, Sessions.id)

    async def count_usage(
        self,
        scope: InsightScope,
        window: InsightWindow,
        granularity: Granularity,
    ) -> UsageSummary:
        scoped = self._scoped_questions(scope, window).subquery("scoped")

        totals_stmt = sa.select(
            sa.func.count().label("questions"),
            sa.func.count(sa.distinct(scoped.c.session_id)).label("conversations"),
            sa.func.coalesce(
                sa.func.sum(sa.case((scoped.c.is_followup, 1), else_=0)), 0
            ).label("followups"),
            sa.func.count(sa.distinct(scoped.c.user_id)).label("users"),
            sa.func.count(
                sa.distinct(
                    sa.case((scoped.c.api_key_id.isnot(None), scoped.c.session_id))
                )
            ).label("api_key_conversations"),
        )
        totals = (await self.session.execute(totals_stmt)).one()

        # ``timezone(tz, timestamptz)`` yields the wall-clock time in ``tz``
        # so buckets follow the operator's calendar days, not UTC's.
        local_time = sa.func.timezone(window.timezone, scoped.c.created_at)
        bucket = sa.func.date_trunc(granularity, local_time).label("bucket")
        buckets_stmt = (
            sa.select(
                bucket,
                sa.func.count(sa.distinct(scoped.c.session_id)).label("conversations"),
                sa.func.count().label("questions"),
                sa.func.count(sa.distinct(scoped.c.user_id)).label("users"),
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        bucket_rows = (await self.session.execute(buckets_stmt)).all()

        return UsageSummary(
            conversations=int(totals.conversations),
            questions=int(totals.questions),
            followups=int(totals.followups),
            users=int(totals.users),
            api_key_conversations=int(totals.api_key_conversations),
            buckets=[
                UsageBucket(
                    bucket_start=row.bucket,
                    conversations=int(row.conversations),
                    questions=int(row.questions),
                    users=int(row.users),
                )
                for row in bucket_rows
            ],
        )

    async def list_questions(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        include_followups: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[QuestionRow], int]:
        """Newest first. Returns ``(page, total)``."""
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        base = sa.select(scoped)
        if not include_followups:
            base = base.where(~scoped.c.is_followup)

        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        page_stmt = (
            base.order_by(scoped.c.created_at.desc(), scoped.c.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(page_stmt)).all()
        return (
            [
                QuestionRow(
                    created_at=row.created_at,
                    session_id=row.session_id,
                    question=row.question,
                    is_followup=bool(row.is_followup),
                )
                for row in rows
            ],
            int(total or 0),
        )

    async def top_questions(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        n: int,
        include_followups: bool,
        sample_sessions: int = 3,
    ) -> tuple[list[TopQuestionRow], int]:
        """Exact-text groups after normalisation. Returns ``(rows, total)``
        where ``total`` is the number of questions the shares are relative to.
        """
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        normalized = normalized_question_expr(scoped.c.question).label("normalized")
        stmt = sa.select(
            normalized,
            # "occurrences", not "count": Row exposes tuple.count as a method.
            sa.func.count().label("occurrences"),
            sa.func.count(sa.distinct(scoped.c.session_id)).label("conversations"),
            sa.func.min(scoped.c.question).label("display_text"),
            sa.func.array_agg(
                sa.distinct(scoped.c.session_id), type_=sa.ARRAY(sa.UUID())
            )[1:sample_sessions].label("sample_session_ids"),
            sa.func.sum(sa.func.count()).over().label("total"),
        )
        if not include_followups:
            stmt = stmt.where(~scoped.c.is_followup)
        stmt = (
            stmt.group_by(normalized)
            .order_by(sa.desc("occurrences"), sa.asc("display_text"))
            .limit(n)
        )
        rows = (await self.session.execute(stmt)).all()
        total = int(rows[0].total) if rows else 0
        return (
            [
                TopQuestionRow(
                    display_text=row.display_text,
                    occurrences=int(row.occurrences),
                    conversations=int(row.conversations),
                    sample_session_ids=list(row.sample_session_ids or []),
                )
                for row in rows
            ],
            total,
        )
