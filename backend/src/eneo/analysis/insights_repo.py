"""Scoped SQL over ``questions`` / ``sessions`` for the insights tools and
the insights figures.

Every query is fixed to one :class:`InsightScope` (tenant + analysed
assistant or group chat) and one :class:`InsightWindow`, except the tenant's
target list, which is fixed to the tenant and the window. The window is
applied on *question* time, not session time, so "yesterday" includes
follow-up questions asked yesterday in conversations that started earlier,
and a conversation counts in every period it had a question in; this
deliberately differs from the Insights tab's older statistics counters,
which count sessions by their start time.

Tenant scoping filters ``Questions.tenant_id`` directly and never joins
``Users``: api-key and widget sessions carry no ``user_id`` and an inner join
would drop them. Every row and figure covers every source unless a read is
asked for one, and each conversation carries its source
(:mod:`eneo.sessions.session_source`).

Every row that carries question or answer text also carries the ids of the
questions that text comes from, so a tool can name the sources of what it
returns. A conversation that is a copy of removed content is no conversation
of the target here: every read leaves it out in the statement that reads the
text (``copy_session_valid``), and a read that takes several statements asks
``readable_sessions`` after the last one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal, NamedTuple, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import LateralFromClause

from eneo.analysis.gap_patterns import NOT_KNOWING_REGEX
from eneo.analysis.insight_scope import InsightScope, InsightTargetKind, InsightWindow
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.data_retention.derivations import copy_session_valid, readable_sessions
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    Assistants,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    QuestionFeedback,
    Questions,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.sessions.hidden_sessions import exclude_hidden_sessions, hidden_session_clause
from eneo.sessions.session_source import (
    SESSION_SOURCES,
    SessionSource,
    has_source,
    session_source,
)

Granularity = Literal["day", "week", "month"]
RatingKind = Literal["answer", "conversation"]
TargetSort = Literal["name", "conversations", "questions"]

__all__ = [
    "ActivityDay",
    "Granularity",
    "InsightScope",
    "InsightWindow",
    "InsightsRepository",
    "KnowledgeSetup",
    "KnowledgeUse",
    "NoKnowledgeRow",
    "PeriodFigures",
    "QuestionRow",
    "RatingKind",
    "RatingRow",
    "RephrasingRow",
    "SearchHit",
    "SourceCounts",
    "TargetRow",
    "TargetSort",
    "TargetUsage",
    "TopQuestionRow",
    "Transcript",
    "TranscriptTurn",
    "UnansweredRow",
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
    """Counts only: no question text, so no sources."""

    conversations: int
    questions: int
    followups: int
    users: int
    api_key_conversations: int
    widget_conversations: int
    buckets: list[UsageBucket]


class QuestionRow(NamedTuple):
    question_id: UUID
    created_at: datetime
    session_id: UUID
    question: str
    is_followup: bool


class TopQuestionRow(NamedTuple):
    display_text: str
    occurrences: int
    conversations: int
    sample_session_ids: list[UUID]
    # Every question of the group: the text shown is each of theirs.
    question_ids: list[UUID]


class SearchHit(NamedTuple):
    question_id: UUID
    created_at: datetime
    session_id: UUID
    question: str
    answer: str
    is_followup: bool
    exact: bool


class TranscriptTurn(NamedTuple):
    question_id: UUID
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
    question_id: UUID
    created_at: datetime
    session_id: UUID
    question: str
    evidence: str


class NoKnowledgeRow(NamedTuple):
    question_id: UUID
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
    # The questions above, in the same order.
    question_ids: list[UUID]


class SourceCounts(NamedTuple):
    total: int
    user: int
    api_key: int
    widget: int


class KnowledgeSetup(NamedTuple):
    """The knowledge a target's answering assistants have now.

    ``inject_assistant_ids`` retrieve on every turn, so each of their answers
    searched, hit or not; tool-mode answers searched only when they called the
    knowledge tool.
    """

    has_knowledge: bool
    inject_assistant_ids: frozenset[UUID]


class KnowledgeUse(NamedTuple):
    searched: int
    missed: int


class PeriodFigures(NamedTuple):
    """Counts only: no question text, so no question ids to name."""

    conversations: SourceCounts
    questions: SourceCounts
    followups: int
    users: int
    single_question_conversations: int
    returning_users: int
    unanswered: int
    knowledge: KnowledgeUse | None
    answers_positive: int
    answers_negative: int
    answers_with_comment: int
    conversations_positive: int
    conversations_negative: int


class ActivityDay(NamedTuple):
    day: date
    conversations: SourceCounts
    questions: SourceCounts


class RatingRow(NamedTuple):
    """One rating: of an answer (``question_id`` is the rated answer's
    question) or of a whole conversation (``question`` is its first question,
    ``question_id`` is None). Never who gave it."""

    kind: RatingKind
    value: int
    comment: str | None
    question: str
    question_id: UUID | None
    session_id: UUID
    source: SessionSource
    rated_at: datetime
    # Unique across both kinds: the question id, or the session id.
    key: UUID


class TargetUsage(NamedTuple):
    conversations: SourceCounts
    questions: int


class TargetRow(NamedTuple):
    id: UUID
    kind: InsightTargetKind
    name: str
    space_id: UUID
    space_name: str
    personal_space: bool
    insight_enabled: bool
    usage: TargetUsage
    previous: TargetUsage
    answers_positive: int
    answers_negative: int


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
# The internal knowledge server as tool calls name it
# (``eneo.internal_mcp.constants.KNOWLEDGE_SERVER_NAME``; importing that
# package here would import the insights tools, which import this module),
# and its tool that searches: the others list or read sources.
KNOWLEDGE_SERVER = "knowledge"
KNOWLEDGE_SEARCH_TOOL = "search_knowledge"


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


def _split_by_source(
    prefix: str,
    count_where: Callable[[sa.ColumnElement[bool]], sa.ColumnElement[Any]],
    source: sa.ColumnElement[Any],
) -> list[sa.Label[Any]]:
    """One count in total and one per source, labelled ``prefix`` and
    ``prefix_<source>``; read back with :func:`_source_counts`."""
    return [count_where(sa.true()).label(prefix)] + [
        count_where(source == name).label(f"{prefix}_{name}")
        for name in SESSION_SOURCES
    ]


def _source_counts(row: sa.Row[Any], prefix: str) -> SourceCounts:
    return SourceCounts(
        total=int(getattr(row, prefix) or 0),
        user=int(getattr(row, f"{prefix}_user") or 0),
        api_key=int(getattr(row, f"{prefix}_api_key") or 0),
        widget=int(getattr(row, f"{prefix}_widget") or 0),
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    @staticmethod
    def _knowledge_passages() -> sa.Subquery:
        """Knowledge passages per question, with the best score among them.

        Knowledge reaches a turn two ways and both count as evidence:
        injected passages are rows in ``info_blob_references``; passages the
        model fetched through the knowledge tool are ``mcp_tool_references``
        with an ``eneo://info-blob/`` URI and their score in ``meta``.
        """
        passages = sa.union_all(
            sa.select(
                InfoBlobReferences.question_id.label("question_id"),
                InfoBlobReferences.similarity_score.label("score"),
            ),
            sa.select(
                McpToolReference.question_id.label("question_id"),
                InsightsRepository._tool_passage_score().label("score"),
            ).where(InsightsRepository._is_knowledge_passage()),
        ).subquery("passages")
        return (
            sa.select(
                passages.c.question_id,
                sa.func.count().label("cited_passages"),
                sa.func.max(passages.c.score).label("best_score"),
            )
            .group_by(passages.c.question_id)
            .subquery("cited")
        )

    @staticmethod
    def _in_scope(
        scope: InsightScope,
        window: InsightWindow,
        source: SessionSource | None = None,
    ) -> list[sa.ColumnElement[bool]]:
        """What makes a question one of the scope's in the window, for a
        statement over ``questions`` joined to ``sessions``: the tenant, the
        target, question time, a readable and not hidden conversation, and
        ``source`` when one is asked for."""
        target = (
            Sessions.assistant_id == scope.target_id
            if scope.kind == "assistant"
            else Sessions.group_chat_id == scope.target_id
        )
        criteria = [
            Questions.tenant_id == scope.tenant_id,
            Questions.question.isnot(None),
            Questions.created_at >= window.start,
            Questions.created_at < window.end,
            copy_session_valid(Sessions.id.expression),
            target,
            hidden_session_clause(Sessions.id),
        ]
        if source is not None:
            criteria.append(has_source(source))
        return criteria

    @staticmethod
    def _is_knowledge_passage() -> sa.ColumnElement[bool]:
        return McpToolReference.uri.like("eneo://info-blob/%")

    @staticmethod
    def _tool_passage_score() -> sa.ColumnElement[float | None]:
        """A knowledge tool passage's score; a contextual neighbour has none."""
        tool_score = McpToolReference.meta["score"]
        return sa.case(
            (sa.func.jsonb_typeof(tool_score) == "number", tool_score.as_float())
        )

    @staticmethod
    def _answer_passages() -> LateralFromClause:
        """The knowledge passages one answer cited and the best score among
        them, injected or fetched through the knowledge tool. Correlated to
        ``questions``: two index probes per answer, never a scan of every
        citation."""
        passages = sa.union_all(
            sa.select(InfoBlobReferences.similarity_score.label("score"))
            .where(InfoBlobReferences.question_id == Questions.id)
            .correlate(Questions),
            sa.select(InsightsRepository._tool_passage_score().label("score"))
            .where(
                McpToolReference.question_id == Questions.id,
                InsightsRepository._is_knowledge_passage(),
            )
            .correlate(Questions),
        ).subquery("passages")
        return (
            sa.select(
                sa.func.count().label("passages"),
                sa.func.max(passages.c.score).label("best_score"),
            )
            .select_from(passages)
            .lateral("cited")
        )

    @staticmethod
    def _knowledge_calls(tool_calls: Any) -> sa.TableValuedAlias:
        """The turn's tool calls, one row each. Turns without tool calls hold
        SQL NULL or a JSON ``null``; only an array can be unnested."""
        return sa.func.jsonb_array_elements(
            sa.case(
                (sa.func.jsonb_typeof(tool_calls) == "array", tool_calls),
                else_=sa.text("'[]'::jsonb"),
            )
        ).table_valued("value")

    @staticmethod
    def _knowledge_no_results(tool_calls: Any) -> sa.ColumnElement[bool]:
        """The knowledge tool answered the turn with no results."""
        call = InsightsRepository._knowledge_calls(tool_calls)
        return sa.exists(
            sa.select(sa.literal(1))
            .select_from(call)
            .where(
                call.c.value.op("->>")("server_name") == KNOWLEDGE_SERVER,
                call.c.value.op("->>")("result").like("No results for%"),
            )
        )

    @staticmethod
    def _knowledge_searched_by_tool(tool_calls: Any) -> sa.ColumnElement[bool]:
        """The turn called the knowledge tool's search."""
        call = InsightsRepository._knowledge_calls(tool_calls)
        return sa.exists(
            sa.select(sa.literal(1))
            .select_from(call)
            .where(
                call.c.value.op("->>")("server_name") == KNOWLEDGE_SERVER,
                call.c.value.op("->>")("tool_name") == KNOWLEDGE_SEARCH_TOOL,
            )
        )

    @staticmethod
    def _is_only_question_expr() -> sa.ColumnElement[bool]:
        """``True`` when the question is the only one in its conversation:
        the conversation ended after the first answer."""
        other = aliased(Questions)
        return ~sa.exists(
            sa.select(other.id).where(
                other.session_id == Questions.session_id, other.id != Questions.id
            )
        )

    def _scoped_questions(
        self,
        scope: InsightScope,
        window: InsightWindow,
        source: SessionSource | None = None,
    ) -> sa.Select[Any]:
        return (
            sa.select(
                Questions.id.label("id"),
                Questions.question.label("question"),
                Questions.created_at.label("created_at"),
                Questions.session_id.label("session_id"),
                Questions.answer.label("answer"),
                Questions.tool_calls.label("tool_calls"),
                Sessions.user_id.label("user_id"),
                session_source().label("source"),
                self._is_followup_expr().label("is_followup"),
            )
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(*self._in_scope(scope, window, source))
        )

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
            sa.func.count(sa.distinct(scoped.c.session_id))
            .filter(scoped.c.source == "api_key")
            .label("api_key_conversations"),
            sa.func.count(sa.distinct(scoped.c.session_id))
            .filter(scoped.c.source == "widget")
            .label("widget_conversations"),
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
            widget_conversations=int(totals.widget_conversations),
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
                    question_id=row.id,
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
            sa.func.array_agg(scoped.c.id, type_=sa.ARRAY(sa.UUID())).label(
                "question_ids"
            ),
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
                    question_ids=list(row.question_ids or []),
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
        exact = scoped.c.question.ilike(f"%{_escape_like(query)}%", escape="\\")
        fuzzy = (
            sa.func.word_similarity(query, scoped.c.question) >= SEARCH_WORD_SIMILARITY
        )
        base = sa.select(
            scoped.c.id,
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
                    question_id=row.id,
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
        missing, hidden, a copy of removed content or outside the scope
        (indistinguishable on purpose)."""
        stmt = sa.select(Sessions.id, Sessions.created_at).where(
            Sessions.id == session_id, copy_session_valid(Sessions.id.expression)
        )
        if scope.kind == "assistant":
            stmt = stmt.where(Sessions.assistant_id == scope.target_id)
        else:
            stmt = stmt.where(Sessions.group_chat_id == scope.target_id)
        stmt = exclude_hidden_sessions(stmt, Sessions.id)
        header = (await self.session.execute(stmt)).first()
        if header is None:
            return None

        cited = self._knowledge_passages()
        turns_stmt = (
            sa.select(
                Questions.id,
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
        # The turns came after the session row's check: ask again, last.
        if not await readable_sessions(self.session, [session_id]):
            return None
        turns = [
            TranscriptTurn(
                question_id=row.id,
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
            scoped.c.id,
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
                base.order_by(scoped.c.created_at.desc(), scoped.c.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return (
            [
                UnansweredRow(
                    question_id=row.id,
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
        per embedding model) or below :data:`KNOWLEDGE_SCORE_FLOOR`. Passages
        count whether they were injected or fetched through the knowledge
        tool. Returns ``(rows, total, window median score)``.
        """
        scoped = self._scoped_questions(scope, window).subquery("scoped")
        cited = self._knowledge_passages()
        no_results = self._knowledge_no_results(scoped.c.tool_calls)
        scored = (
            sa.select(
                scoped.c.id,
                scoped.c.created_at,
                scoped.c.session_id,
                scoped.c.question,
                cited.c.best_score,
                no_results.label("no_results"),
                cited.c.question_id.is_(None).label("uncited"),
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
            scored.c.id,
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
                base.order_by(scored.c.created_at.desc(), scored.c.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return (
            [
                NoKnowledgeRow(
                    question_id=row.id,
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
        in_order = (ordered.c.created_at.asc(), ordered.c.id.asc())
        per_session = (
            sa.select(
                ordered.c.session_id,
                sa.func.min(ordered.c.created_at).label("started_at"),
                sa.func.count().label("question_count"),
                sa.func.sum(similar_pair).label("similar_pairs"),
                sa.func.array_agg(
                    aggregate_order_by(ordered.c.question, *in_order),
                    type_=sa.ARRAY(sa.Text()),
                ).label("questions"),
                sa.func.array_agg(
                    aggregate_order_by(ordered.c.id, *in_order),
                    type_=sa.ARRAY(sa.UUID()),
                ).label("question_ids"),
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
                    per_session.c.session_id.desc(),
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
                    question_ids=list(row.question_ids or []),
                )
                for row in rows
            ],
            int(total or 0),
        )

    async def knowledge_setup(self, scope: InsightScope) -> KnowledgeSetup:
        """Whether the target's answering assistants have knowledge now, and
        which of them retrieve it on every turn: the assistant, or a group
        chat's members."""
        has_knowledge = sa.or_(
            sa.exists().where(AssistantsGroups.assistant_id == Assistants.id),
            sa.exists().where(AssistantsWebsites.assistant_id == Assistants.id),
            sa.exists().where(
                AssistantIntegrationKnowledge.assistant_id == Assistants.id
            ),
        )
        stmt = (
            sa.select(
                Assistants.id,
                Assistants.knowledge_mode,
                has_knowledge.label("has_knowledge"),
            )
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Spaces.tenant_id == scope.tenant_id)
        )
        if scope.kind == "assistant":
            stmt = stmt.where(Assistants.id == scope.target_id)
        else:
            stmt = stmt.where(
                Assistants.id.in_(
                    sa.select(GroupChatsAssistantsMapping.assistant_id).where(
                        GroupChatsAssistantsMapping.group_chat_id == scope.target_id
                    )
                )
            )
        rows = (await self.session.execute(stmt)).all()
        return KnowledgeSetup(
            has_knowledge=any(row.has_knowledge for row in rows),
            inject_assistant_ids=frozenset(
                row.id
                for row in rows
                if row.has_knowledge
                and row.knowledge_mode == KnowledgeMode.INJECT.value
            ),
        )

    async def summarize(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
        knowledge: KnowledgeSetup,
    ) -> PeriodFigures:
        """The figures of one period in one statement.

        Conversations are those with a question in the window. Knowledge uses
        absolute signals only: an answer searched when it cited a passage,
        called the knowledge search, or was given by an assistant that
        retrieves on every turn; it missed when the search reported no
        results, nothing was cited, or the best score is under
        :data:`KNOWLEDGE_SCORE_FLOOR`. Without knowledge the figure is None.
        """
        base = (
            self._scoped_questions(scope, window, source)
            .add_columns(
                self._is_only_question_expr().label("only_question"),
                Sessions.feedback_value.label("conversation_rating"),
                QuestionFeedback.value.label("answer_rating"),
                QuestionFeedback.text.label("answer_comment"),
            )
            .outerjoin(QuestionFeedback, QuestionFeedback.question_id == Questions.id)
        )
        if knowledge.has_knowledge:
            cited = self._answer_passages()
            base = base.add_columns(
                cited.c.passages,
                cited.c.best_score,
                self._knowledge_no_results(Questions.tool_calls).label("no_results"),
                self._knowledge_searched_by_tool(Questions.tool_calls).label(
                    "tool_searched"
                ),
                Questions.assistant_id.label("answering_assistant_id"),
            ).join(cited, sa.true())
        scoped = base.cte("scoped")
        s = scoped.c

        local_day = sa.cast(sa.func.timezone(window.timezone, s.created_at), sa.Date)
        returning_users = (
            sa.select(sa.func.count())
            .select_from(
                sa.select(s.user_id)
                .where(s.user_id.is_not(None))
                .group_by(s.user_id)
                .having(sa.func.count(sa.distinct(local_day)) > 1)
                .subquery("returning")
            )
            .scalar_subquery()
        )
        has_comment = sa.func.coalesce(sa.func.btrim(s.answer_comment), "") != ""
        columns: list[sa.ColumnElement[Any]] = [
            *_split_by_source(
                "questions", lambda where: sa.func.count().filter(where), s.source
            ),
            *_split_by_source(
                "conversations",
                lambda where: sa.func.count(sa.distinct(s.session_id)).filter(where),
                s.source,
            ),
            sa.func.count().filter(s.is_followup).label("followups"),
            sa.func.count(sa.distinct(s.user_id)).label("users"),
            sa.func.count()
            .filter(s.only_question)
            .label("single_question_conversations"),
            returning_users.label("returning_users"),
            sa.func.count()
            .filter(s.answer.op("~*")(NOT_KNOWING_REGEX))
            .label("unanswered"),
            sa.func.count().filter(s.answer_rating == 1).label("answers_positive"),
            sa.func.count().filter(s.answer_rating == -1).label("answers_negative"),
            sa.func.count()
            .filter(s.answer_rating.is_not(None), has_comment)
            .label("answers_with_comment"),
            sa.func.count(sa.distinct(s.session_id))
            .filter(s.conversation_rating == 1)
            .label("conversations_positive"),
            sa.func.count(sa.distinct(s.session_id))
            .filter(s.conversation_rating == -1)
            .label("conversations_negative"),
        ]
        if knowledge.has_knowledge:
            injects = (
                s.answering_assistant_id.in_(sorted(knowledge.inject_assistant_ids))
                if knowledge.inject_assistant_ids
                else sa.false()
            )
            searched = sa.or_(s.passages > 0, s.tool_searched, injects)
            weak = sa.and_(
                s.best_score.is_not(None), s.best_score < KNOWLEDGE_SCORE_FLOOR
            )
            missed = sa.and_(searched, sa.or_(s.no_results, s.passages == 0, weak))
            columns += [
                sa.func.count().filter(searched).label("knowledge_searched"),
                sa.func.count().filter(missed).label("knowledge_missed"),
            ]

        row = (await self.session.execute(sa.select(*columns))).one()
        return PeriodFigures(
            conversations=_source_counts(row, "conversations"),
            questions=_source_counts(row, "questions"),
            followups=int(row.followups),
            users=int(row.users),
            single_question_conversations=int(row.single_question_conversations),
            returning_users=int(row.returning_users or 0),
            unanswered=int(row.unanswered),
            knowledge=(
                KnowledgeUse(
                    searched=int(row.knowledge_searched),
                    missed=int(row.knowledge_missed),
                )
                if knowledge.has_knowledge
                else None
            ),
            answers_positive=int(row.answers_positive),
            answers_negative=int(row.answers_negative),
            answers_with_comment=int(row.answers_with_comment),
            conversations_positive=int(row.conversations_positive),
            conversations_negative=int(row.conversations_negative),
        )

    async def count_activity(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
    ) -> list[ActivityDay]:
        """Conversations and questions per local day in the window's zone,
        split by source; days without questions are left out. A conversation
        counts on every day it had a question."""
        scoped = self._scoped_questions(scope, window, source).subquery("scoped")
        day = sa.cast(
            sa.func.timezone(window.timezone, scoped.c.created_at), sa.Date
        ).label("day")
        stmt = (
            sa.select(
                day,
                *_split_by_source(
                    "questions",
                    lambda where: sa.func.count().filter(where),
                    scoped.c.source,
                ),
                *_split_by_source(
                    "conversations",
                    lambda where: sa.func.count(
                        sa.distinct(scoped.c.session_id)
                    ).filter(where),
                    scoped.c.source,
                ),
            )
            .group_by(day)
            .order_by(day)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ActivityDay(
                day=row.day,
                conversations=_source_counts(row, "conversations"),
                questions=_source_counts(row, "questions"),
            )
            for row in rows
        ]

    async def list_ratings(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
        value: Literal[-1, 1] | None,
        has_comment: bool | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> tuple[list[RatingRow], int, bool]:
        """Answer and conversation ratings, newest rating first. Returns
        ``(page, total, has_more)``.

        An answer rating belongs to the window of its question; a
        conversation rating to every window the conversation had a question
        in, as the figures count it. ``after`` is the ``(rated_at, key)`` of
        the previous page's last row.
        """
        in_scope = self._in_scope(scope, window, source)
        answers = (
            sa.select(
                sa.literal("answer", sa.String).label("kind"),
                QuestionFeedback.value.label("value"),
                QuestionFeedback.text.label("comment"),
                Questions.question.label("question"),
                Questions.id.label("question_id"),
                Questions.session_id.label("session_id"),
                session_source().label("source"),
                QuestionFeedback.updated_at.label("rated_at"),
                Questions.id.label("key"),
            )
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(QuestionFeedback, QuestionFeedback.question_id == Questions.id)
            .where(*in_scope)
        )
        active = (
            sa.select(Questions.session_id)
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(*in_scope)
            .correlate(None)
        )
        first_question = (
            sa.select(Questions.question)
            .where(Questions.session_id == Sessions.id)
            .order_by(Questions.created_at.asc(), Questions.id.asc())
            .limit(1)
            .correlate(Sessions)
            .scalar_subquery()
        )
        conversations = sa.select(
            sa.literal("conversation", sa.String).label("kind"),
            Sessions.feedback_value.label("value"),
            Sessions.feedback_text.label("comment"),
            first_question.label("question"),
            sa.cast(sa.null(), sa.Uuid()).label("question_id"),
            Sessions.id.label("session_id"),
            session_source().label("source"),
            # The stored feedback time: a widget vote without a comment keeps
            # the time of the comment before it, or of the conversation's start.
            Sessions.feedback_set_at.label("rated_at"),
            Sessions.id.label("key"),
        ).where(Sessions.feedback_value.is_not(None), Sessions.id.in_(active))
        ratings = sa.union_all(answers, conversations).subquery("ratings")
        r = ratings.c

        filters: list[sa.ColumnElement[bool]] = []
        if value is not None:
            filters.append(r.value == value)
        if has_comment is not None:
            commented = sa.func.coalesce(sa.func.btrim(r.comment), "") != ""
            filters.append(commented if has_comment else sa.not_(commented))

        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(ratings).where(*filters)
        )
        page = sa.select(ratings).where(*filters)
        if after is not None:
            page = page.where(
                sa.tuple_(r.rated_at, r.key)
                < sa.tuple_(sa.literal(after[0]), sa.literal(after[1], sa.Uuid()))
            )
        page = page.order_by(r.rated_at.desc(), r.key.desc()).limit(limit + 1)
        rows = (await self.session.execute(page)).all()
        return (
            [
                RatingRow(
                    kind=cast(RatingKind, row.kind),
                    value=int(row.value),
                    comment=row.comment,
                    question=row.question or "",
                    question_id=row.question_id,
                    session_id=row.session_id,
                    source=cast(SessionSource, row.source),
                    rated_at=row.rated_at,
                    key=row.key,
                )
                for row in rows[:limit]
            ],
            int(total or 0),
            len(rows) > limit,
        )

    async def list_targets(
        self,
        *,
        tenant_id: UUID,
        window: InsightWindow,
        previous: InsightWindow | None,
        query: str | None,
        unused_only: bool,
        sort: TargetSort,
        descending: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[TargetRow], int]:
        """Every assistant people see and every group chat of the tenant,
        with its usage in the window (and the previous window), in one
        statement. Returns ``(page, total)``.

        The tenant's questions in both windows are read once and grouped per
        conversation, then per target; only the conversation rows are checked
        for the hidden-session rule and the copy check.
        """
        current = Questions.created_at >= window.start
        per_session = (
            sa.select(
                Questions.session_id.label("session_id"),
                sa.func.count().filter(current).label("questions"),
                sa.func.count().filter(sa.not_(current)).label("previous_questions"),
                sa.func.count()
                .filter(current, QuestionFeedback.value == 1)
                .label("positive"),
                sa.func.count()
                .filter(current, QuestionFeedback.value == -1)
                .label("negative"),
            )
            .select_from(Questions)
            .outerjoin(QuestionFeedback, QuestionFeedback.question_id == Questions.id)
            .where(
                Questions.tenant_id == tenant_id,
                Questions.session_id.is_not(None),
                Questions.question.isnot(None),
                Questions.created_at
                >= (previous.start if previous is not None else window.start),
                Questions.created_at < window.end,
            )
            .group_by(Questions.session_id)
            .subquery("per_session")
        )
        ps = per_session.c
        target_id = sa.func.coalesce(Sessions.group_chat_id, Sessions.assistant_id)
        source = session_source()
        per_target = (
            sa.select(
                target_id.label("target_id"),
                *_split_by_source(
                    "conversations",
                    lambda where: sa.func.count().filter(ps.questions > 0, where),
                    source,
                ),
                sa.func.sum(ps.questions).label("questions"),
                *_split_by_source(
                    "previous_conversations",
                    lambda where: sa.func.count().filter(
                        ps.previous_questions > 0, where
                    ),
                    source,
                ),
                sa.func.sum(ps.previous_questions).label("previous_questions"),
                sa.func.sum(ps.positive).label("positive"),
                sa.func.sum(ps.negative).label("negative"),
            )
            .select_from(per_session)
            .join(Sessions, Sessions.id == ps.session_id)
            # On the grouped conversations, so the checks run once for each
            # conversation of the window and never for the rest of the table.
            .where(
                hidden_session_clause(ps.session_id),
                copy_session_valid(ps.session_id),
            )
            .group_by(target_id)
            .subquery("per_target")
        )

        personal_space = Spaces.user_id.is_not(None)
        targets = sa.union_all(
            sa.select(
                Assistants.id.label("id"),
                sa.literal("assistant", sa.String).label("kind"),
                Assistants.name.label("name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                personal_space.label("personal_space"),
                Assistants.insight_enabled.label("insight_enabled"),
            )
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Spaces.tenant_id == tenant_id, Assistants.hidden.is_(False)),
            sa.select(
                GroupChatsTable.id.label("id"),
                sa.literal("group_chat", sa.String).label("kind"),
                GroupChatsTable.name.label("name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                personal_space.label("personal_space"),
                GroupChatsTable.insight_enabled.label("insight_enabled"),
            )
            .join(Spaces, Spaces.id == GroupChatsTable.space_id)
            .where(Spaces.tenant_id == tenant_id),
        ).subquery("targets")
        t = targets.c
        figures = [column for column in per_target.c if column.name != "target_id"]
        listing = sa.select(
            t.id,
            t.kind,
            t.name,
            t.space_id,
            t.space_name,
            t.personal_space,
            t.insight_enabled,
            *(sa.func.coalesce(column, 0).label(column.name) for column in figures),
        ).outerjoin(per_target, per_target.c.target_id == t.id)
        if query:
            listing = listing.where(
                t.name.ilike(f"%{_escape_like(query)}%", escape="\\")
            )
        if unused_only:
            listing = listing.where(
                sa.func.coalesce(per_target.c.conversations, 0) == 0
            )
        listed = listing.cte("listing")
        lc = listed.c
        sort_key = {
            "name": sa.func.lower(lc.name),
            "conversations": lc.conversations,
            "questions": lc.questions,
        }[sort]
        page = (
            sa.select(listed)
            .order_by(
                sort_key.desc() if descending else sort_key.asc(),
                sa.func.lower(lc.name).asc(),
                lc.id.asc(),
            )
            .offset(offset)
            .limit(limit)
            .lateral("page")
        )
        totals = sa.select(sa.func.count().label("total")).select_from(listed)
        totals_sq = totals.subquery("totals")
        # One row even for an empty page, so the total always comes back.
        stmt = (
            sa.select(totals_sq.c.total, page)
            .select_from(totals_sq)
            .outerjoin(page, sa.true())
        )
        rows = (await self.session.execute(stmt)).all()
        total = int(rows[0].total) if rows else 0
        return (
            [
                TargetRow(
                    id=row.id,
                    kind=cast(InsightTargetKind, row.kind),
                    name=row.name,
                    space_id=row.space_id,
                    space_name=row.space_name,
                    personal_space=bool(row.personal_space),
                    insight_enabled=bool(row.insight_enabled),
                    usage=TargetUsage(
                        conversations=_source_counts(row, "conversations"),
                        questions=int(row.questions),
                    ),
                    previous=TargetUsage(
                        conversations=_source_counts(row, "previous_conversations"),
                        questions=int(row.previous_questions),
                    ),
                    answers_positive=int(row.positive),
                    answers_negative=int(row.negative),
                )
                for row in rows
                if row.id is not None
            ],
            total,
        )
