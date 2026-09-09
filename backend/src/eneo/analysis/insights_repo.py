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
from typing import Any, Literal, NamedTuple, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from eneo.analysis.gap_patterns import NOT_KNOWING_REGEX
from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import InfoBlobReferences, Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.sessions.hidden_sessions import exclude_hidden_sessions

Granularity = Literal["day", "week", "month"]

__all__ = [
    "Granularity",
    "NoKnowledgeRow",
    "RephrasingRow",
    "SearchHit",
    "Transcript",
    "TranscriptTurn",
    "UnansweredRow",
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


class SearchHit(NamedTuple):
    created_at: datetime
    session_id: UUID
    question: str
    answer: str
    is_followup: bool
    exact: bool


class TranscriptTurn(NamedTuple):
    created_at: datetime
    question: str
    answer: str
    cited_passages: int
    best_score: float | None
    tool_names: list[str]


class Transcript(NamedTuple):
    session_id: UUID
    started_at: datetime
    turns: list[TranscriptTurn]


class UnansweredRow(NamedTuple):
    created_at: datetime
    session_id: UUID
    question: str
    evidence: str


class NoKnowledgeRow(NamedTuple):
    created_at: datetime
    session_id: UUID
    question: str
    reason: str
    best_score: float | None


class RephrasingRow(NamedTuple):
    session_id: UUID
    started_at: datetime
    questions: list[str]
    similar_pairs: int


# Trigram thresholds. word_similarity finds a query phrase inside a longer
# question; similarity compares two whole questions. Both are deliberately
# loose: the tools return candidates for the model to judge.
SEARCH_WORD_SIMILARITY = 0.45
REPHRASING_SIMILARITY = 0.3
# A citation score below this is a poor match on any embedding model.
KNOWLEDGE_SCORE_FLOOR = 0.2
# Sequence of questions in one conversation that suggests rephrasing even
# when no pair is textually similar.
LONG_CONVERSATION_QUESTIONS = 5


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


def _tool_names(tool_calls: object) -> list[str]:
    """``server.tool`` per persisted call; tolerant of older row shapes."""
    if not isinstance(tool_calls, list):
        return []
    names: list[str] = []
    for call in cast(list[object], tool_calls):
        if isinstance(call, dict):
            call_dict = cast(dict[str, object], call)
            names.append(f"{call_dict.get('server_name')}.{call_dict.get('tool_name')}")
    return names


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
                Questions.answer.label("answer"),
                Questions.tool_calls.label("tool_calls"),
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

    async def search_questions(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        query: str,
        offset: int,
        limit: int,
    ) -> tuple[list[SearchHit], int]:
        """Substring hits first, then trigram matches, newest first within each."""
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        exact = scoped.c.question.ilike(f"%{escaped}%", escape="\\")
        fuzzy = (
            sa.func.word_similarity(query, scoped.c.question) >= SEARCH_WORD_SIMILARITY
        )
        base = sa.select(
            scoped.c.created_at,
            scoped.c.session_id,
            scoped.c.question,
            scoped.c.answer,
            scoped.c.is_followup,
            exact.label("exact"),
        ).where(sa.or_(exact, fuzzy))
        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        rows = (
            await self.session.execute(
                base.order_by(
                    sa.desc("exact"), scoped.c.created_at.desc(), scoped.c.id.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return (
            [
                SearchHit(
                    created_at=row.created_at,
                    session_id=row.session_id,
                    question=row.question,
                    answer=row.answer or "",
                    is_followup=bool(row.is_followup),
                    exact=bool(row.exact),
                )
                for row in rows
            ],
            int(total or 0),
        )

    async def get_transcript(
        self, scope: InsightScope, session_id: UUID
    ) -> Transcript | None:
        """Every turn of one conversation, or ``None`` when the session is
        missing, hidden or outside the scope (indistinguishable on purpose)."""
        stmt = sa.select(Sessions.id, Sessions.created_at).where(
            Sessions.id == session_id
        )
        if scope.kind == "assistant":
            stmt = stmt.where(Sessions.assistant_id == scope.target_id)
        else:
            stmt = stmt.where(Sessions.group_chat_id == scope.target_id)
        stmt = exclude_hidden_sessions(stmt, Sessions.id)
        header = (await self.session.execute(stmt)).first()
        if header is None:
            return None

        cited = (
            sa.select(
                InfoBlobReferences.question_id.label("question_id"),
                sa.func.count().label("cited_passages"),
                sa.func.max(InfoBlobReferences.similarity_score).label("best_score"),
            )
            .group_by(InfoBlobReferences.question_id)
            .subquery("cited")
        )
        turns_stmt = (
            sa.select(
                Questions.created_at,
                Questions.question,
                Questions.answer,
                Questions.tool_calls,
                sa.func.coalesce(cited.c.cited_passages, 0).label("cited_passages"),
                cited.c.best_score,
            )
            .outerjoin(cited, cited.c.question_id == Questions.id)
            .where(
                Questions.session_id == session_id,
                Questions.tenant_id == scope.tenant_id,
            )
            .order_by(Questions.created_at.asc(), Questions.id.asc())
        )
        rows = (await self.session.execute(turns_stmt)).all()
        turns = [
            TranscriptTurn(
                created_at=row.created_at,
                question=row.question or "",
                answer=row.answer or "",
                cited_passages=int(row.cited_passages),
                best_score=float(row.best_score)
                if row.best_score is not None
                else None,
                tool_names=_tool_names(row.tool_calls),
            )
            for row in rows
        ]
        return Transcript(
            session_id=header.id, started_at=header.created_at, turns=turns
        )

    async def find_unanswered(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[UnansweredRow], int]:
        """Turns whose answer admits not knowing, with the matched phrase."""
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        base = sa.select(
            scoped.c.created_at,
            scoped.c.session_id,
            scoped.c.question,
            # substring(text from regex) returns the first parenthesised group,
            # so wrap the whole alternation in one group to get the full match.
            sa.func.substring(scoped.c.answer, f"({NOT_KNOWING_REGEX})").label(
                "evidence"
            ),
        ).where(scoped.c.answer.op("~*")(NOT_KNOWING_REGEX))
        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        rows = (
            await self.session.execute(
                base.order_by(scoped.c.created_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        return (
            [
                UnansweredRow(
                    created_at=row.created_at,
                    session_id=row.session_id,
                    question=row.question,
                    evidence=row.evidence or "",
                )
                for row in rows
            ],
            int(total or 0),
        )

    async def find_no_knowledge(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[NoKnowledgeRow], int, float | None]:
        """Turns answered without a usable knowledge hit.

        Three signals, weakest last: the knowledge tool reported no results;
        the answer cited no knowledge at all; or its best citation score is in
        the window's weakest quartile (relative, because score scales differ
        per embedding model) or below :data:`KNOWLEDGE_SCORE_FLOOR`. Returns
        ``(rows, total, window median score)``.
        """
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        cited = (
            sa.select(
                InfoBlobReferences.question_id.label("question_id"),
                sa.func.max(InfoBlobReferences.similarity_score).label("best_score"),
            )
            .group_by(InfoBlobReferences.question_id)
            .subquery("cited")
        )
        knowledge_refs = sa.exists(
            sa.select(McpToolReference.id).where(
                McpToolReference.question_id == scoped.c.id,
                McpToolReference.uri.like("eneo://info-blob/%"),
            )
        )
        call = sa.func.jsonb_array_elements(
            sa.func.coalesce(scoped.c.tool_calls, sa.text("'[]'::jsonb"))
        ).table_valued("value")
        no_results = sa.exists(
            sa.select(sa.literal(1))
            .select_from(call)
            .where(
                call.c.value.op("->>")("server_name") == "knowledge",
                call.c.value.op("->>")("result").like("No results for%"),
            )
        )
        scored = (
            sa.select(
                scoped.c.id,
                scoped.c.created_at,
                scoped.c.session_id,
                scoped.c.question,
                cited.c.best_score,
                no_results.label("no_results"),
                sa.and_(cited.c.best_score.is_(None), ~knowledge_refs).label("uncited"),
            )
            .outerjoin(cited, cited.c.question_id == scoped.c.id)
            .subquery("scored")
        )
        quartile, median = (
            await self.session.execute(
                sa.select(
                    sa.func.percentile_cont(0.25).within_group(scored.c.best_score),
                    sa.func.percentile_cont(0.5).within_group(scored.c.best_score),
                ).where(scored.c.best_score.isnot(None))
            )
        ).one()
        weak = sa.and_(
            scored.c.best_score.isnot(None),
            sa.or_(
                scored.c.best_score < KNOWLEDGE_SCORE_FLOOR,
                scored.c.best_score <= quartile if quartile is not None else sa.false(),
            ),
        )
        reason = sa.case(
            (scored.c.no_results, sa.literal("knowledge search returned no results")),
            (scored.c.uncited, sa.literal("answer cited no knowledge")),
            (weak, sa.literal("weak best citation score")),
        ).label("reason")
        base = sa.select(
            scored.c.created_at,
            scored.c.session_id,
            scored.c.question,
            scored.c.best_score,
            reason,
        ).where(sa.or_(scored.c.no_results, scored.c.uncited, weak))
        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        rows = (
            await self.session.execute(
                base.order_by(scored.c.created_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        return (
            [
                NoKnowledgeRow(
                    created_at=row.created_at,
                    session_id=row.session_id,
                    question=row.question,
                    reason=row.reason,
                    best_score=float(row.best_score)
                    if row.best_score is not None
                    else None,
                )
                for row in rows
            ],
            int(total or 0),
            float(median) if median is not None else None,
        )

    async def find_rephrasing(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[RephrasingRow], int]:
        """Conversations where the user seems to have asked the same thing
        again: at least three questions with a textually similar consecutive
        pair first, then long conversations without one."""
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        previous = (
            sa.func.lag(scoped.c.question)
            .over(
                partition_by=scoped.c.session_id,
                order_by=(scoped.c.created_at.asc(), scoped.c.id.asc()),
            )
            .label("previous")
        )
        ordered = sa.select(
            scoped.c.session_id,
            scoped.c.question,
            scoped.c.created_at,
            scoped.c.id,
            previous,
        ).subquery("ordered")
        similar_pair = sa.case(
            (
                sa.and_(
                    ordered.c.previous.isnot(None),
                    sa.func.similarity(ordered.c.previous, ordered.c.question)
                    >= REPHRASING_SIMILARITY,
                ),
                1,
            ),
            else_=0,
        )
        per_session = (
            sa.select(
                ordered.c.session_id,
                sa.func.min(ordered.c.created_at).label("started_at"),
                sa.func.count().label("question_count"),
                sa.func.sum(similar_pair).label("similar_pairs"),
                sa.func.array_agg(
                    aggregate_order_by(
                        ordered.c.question,
                        ordered.c.created_at.asc(),
                        ordered.c.id.asc(),
                    ),
                    type_=sa.ARRAY(sa.Text()),
                ).label("questions"),
            )
            .group_by(ordered.c.session_id)
            .subquery("per_session")
        )
        base = sa.select(per_session).where(
            sa.or_(
                sa.and_(
                    per_session.c.question_count >= 3, per_session.c.similar_pairs >= 1
                ),
                per_session.c.question_count >= LONG_CONVERSATION_QUESTIONS,
            )
        )
        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        rows = (
            await self.session.execute(
                base.order_by(
                    sa.desc(per_session.c.similar_pairs > 0),
                    per_session.c.similar_pairs.desc(),
                    per_session.c.question_count.desc(),
                    per_session.c.started_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return (
            [
                RephrasingRow(
                    session_id=row.session_id,
                    started_at=row.started_at,
                    questions=list(row.questions or []),
                    similar_pairs=int(row.similar_pairs or 0),
                )
                for row in rows
            ],
            int(total or 0),
        )
