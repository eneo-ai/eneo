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
from eneo.analysis.insight_scope import (
    InsightScope,
    InsightTargetKind,
    InsightWindow,
    KnowledgeSourceKind,
    MissReason,
)
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.data_retention.derivations import copy_session_valid, readable_sessions
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    Assistants,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    QuestionFeedback,
    Questions,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.websites_table import Websites
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
    "KnowledgeCitations",
    "KnowledgeSetup",
    "KnowledgeSourceKind",
    "KnowledgeSourceRow",
    "KnowledgeUse",
    "MissReason",
    "NoKnowledgeRow",
    "PeriodFigures",
    "QuestionGroupRow",
    "QuestionRow",
    "RatingKind",
    "RatingRow",
    "RephrasingRow",
    "SearchHit",
    "SourceCounts",
    "TargetRow",
    "TargetSort",
    "TargetTotals",
    "TargetUsage",
    "ToolUseRow",
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
    source: SessionSource
    # The answer's rating (1 or -1), None when unrated.
    rating: int | None


class NoKnowledgeRow(NamedTuple):
    question_id: UUID
    created_at: datetime
    session_id: UUID
    question: str
    reason: MissReason
    best_score: float | None
    source: SessionSource
    # The answer's rating (1 or -1), None when unrated.
    rating: int | None


class RephrasingRow(NamedTuple):
    session_id: UUID
    started_at: datetime
    questions: list[str]
    similar_pairs: int
    # The questions above, in the same order.
    question_ids: list[UUID]
    source: SessionSource


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
    answers_negative_with_comment: int
    conversations_positive: int
    conversations_negative: int
    conversations_with_comment: int
    conversations_negative_with_comment: int


class QuestionGroupRow(NamedTuple):
    """One exact-text question group and how its answers fared: one of its
    questions as display text, otherwise counts."""

    display_text: str
    occurrences: int
    conversations: int
    sample_session_id: UUID
    unanswered: int
    answers_positive: int
    answers_negative: int
    knowledge: KnowledgeUse | None


class KnowledgeSourceRow(NamedTuple):
    """A collection, website or integration knowledge and the answers of the
    period that cited a passage from it."""

    kind: KnowledgeSourceKind
    id: UUID
    name: str
    answers: int
    # Attached to the target's answering assistants now.
    attached: bool


class KnowledgeCitations(NamedTuple):
    """Counts and source names only: no conversation text."""

    answers: int
    # Answers that cited a passage of a source that still exists.
    citing_answers: int
    # Every cited source, most cited first.
    cited: list[KnowledgeSourceRow]
    # Attached sources no answer of the period cited, by name.
    unused: list[KnowledgeSourceRow]


class ToolUseRow(NamedTuple):
    """Calls of one capability (``purpose`` set) or of one server's tool.
    Counts and configured names only."""

    purpose: str | None
    server_name: str | None
    tool_name: str | None
    title: str | None
    calls: int
    failed: int
    denied: int


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
    # The question whose text ``question`` is: the rated answer's question,
    # or a conversation rating's first question.
    quoted_question_id: UUID


class TargetUsage(NamedTuple):
    conversations: SourceCounts
    questions: int


class TargetTotals(NamedTuple):
    """Usage of every target a target list matched, not only its page."""

    usage: TargetUsage
    previous: TargetUsage


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
# A Skill's activation is recorded as a call of this tool
# (``eneo.completion_models.domain.skill_activation``); it is a step of the
# answer, not a tool anyone attached.
SKILL_ACTIVATION_TOOL = "eneo_activate_skill"
# A passage the knowledge tool returned names its info blob in its URI,
# optionally followed by ``#chunk-<n>``.
INFO_BLOB_URI_PREFIX = "eneo://info-blob/"
_INFO_BLOB_URI = (
    "^eneo://info-blob/"
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


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


def _has_text(column: Any) -> sa.ColumnElement[bool]:
    """A comment counts when it holds more than whitespace."""
    return sa.func.coalesce(sa.func.btrim(column), "") != ""


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
        return McpToolReference.uri.like(f"{INFO_BLOB_URI_PREFIX}%")

    @staticmethod
    def _tool_passage_score() -> sa.ColumnElement[float | None]:
        """A knowledge tool passage's score; a contextual neighbour has none."""
        tool_score = McpToolReference.meta["score"]
        return sa.case(
            (sa.func.jsonb_typeof(tool_score) == "number", tool_score.as_float())
        )

    @staticmethod
    def _tool_passage_blob() -> sa.ColumnElement[UUID | None]:
        """The info blob a knowledge tool passage comes from, read from its
        URI; None for a URI that names no blob."""
        uri = McpToolReference.uri
        return sa.case(
            (
                uri.op("~")(_INFO_BLOB_URI),
                sa.cast(
                    sa.func.substr(uri, len(INFO_BLOB_URI_PREFIX) + 1, 36), sa.Uuid()
                ),
            )
        )

    @staticmethod
    def _cited_passages() -> sa.CompoundSelect[Any]:
        """The knowledge passages one answer cited, one row each with its info
        blob and score.

        Knowledge reaches a turn two ways and both count as evidence:
        injected passages are rows in ``info_blob_references``; passages the
        model fetched through the knowledge tool are ``mcp_tool_references``
        with an ``eneo://info-blob/`` URI and their score in ``meta``.
        Correlated to ``questions``: two index probes per answer, never a scan
        of every citation.
        """
        return sa.union_all(
            sa.select(
                InfoBlobReferences.info_blob_id.label("info_blob_id"),
                InfoBlobReferences.similarity_score.label("score"),
            )
            .where(InfoBlobReferences.question_id == Questions.id)
            .correlate(Questions),
            sa.select(
                InsightsRepository._tool_passage_blob().label("info_blob_id"),
                InsightsRepository._tool_passage_score().label("score"),
            )
            .where(
                McpToolReference.question_id == Questions.id,
                InsightsRepository._is_knowledge_passage(),
            )
            .correlate(Questions),
        )

    @staticmethod
    def _answer_passages() -> LateralFromClause:
        """How many knowledge passages one answer cited (:meth:`_cited_passages`)
        and the best score among them."""
        passages = InsightsRepository._cited_passages().subquery("passages")
        return (
            sa.select(
                sa.func.count().label("passages"),
                sa.func.max(passages.c.score).label("best_score"),
            )
            .select_from(passages)
            .lateral("cited")
        )

    @staticmethod
    def _turn_calls(tool_calls: Any) -> sa.TableValuedAlias:
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
        call = InsightsRepository._turn_calls(tool_calls)
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
        call = InsightsRepository._turn_calls(tool_calls)
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

    def _with_answer_rating(self, base: sa.Select[Any]) -> sa.Select[Any]:
        """``base`` (a statement over ``questions``) with each answer's rating
        as ``rating``, None when unrated."""
        return base.add_columns(QuestionFeedback.value.label("rating")).outerjoin(
            QuestionFeedback, QuestionFeedback.question_id == Questions.id
        )

    def _with_knowledge_signals(self, base: sa.Select[Any]) -> sa.Select[Any]:
        """``base`` (a statement over ``questions``) with what an answer's
        knowledge verdict (:meth:`_knowledge_verdict`) reads: the passages it
        cited and their best score, whether the knowledge search reported no
        results or ran at all, and the answering assistant."""
        cited = self._answer_passages()
        return base.add_columns(
            cited.c.passages,
            cited.c.best_score,
            self._knowledge_no_results(Questions.tool_calls).label("no_results"),
            self._knowledge_searched_by_tool(Questions.tool_calls).label(
                "tool_searched"
            ),
            Questions.assistant_id.label("answering_assistant_id"),
        ).join(cited, sa.true())

    @staticmethod
    def _knowledge_verdict(
        columns: Any, knowledge: KnowledgeSetup
    ) -> tuple[sa.ColumnElement[bool], sa.ColumnElement[bool]]:
        """Whether an answer searched the knowledge and whether it missed, by
        absolute signals only, over the columns
        :meth:`_with_knowledge_signals` adds.

        An answer searched when it cited a passage, called the knowledge
        search, or was given by an assistant that retrieves on every turn; it
        missed when it searched and the search reported no results, nothing
        was cited, or the best score is under :data:`KNOWLEDGE_SCORE_FLOOR`.
        """
        injects = (
            columns.answering_assistant_id.in_(sorted(knowledge.inject_assistant_ids))
            if knowledge.inject_assistant_ids
            else sa.false()
        )
        searched = sa.or_(columns.passages > 0, columns.tool_searched, injects)
        missed = sa.and_(
            searched,
            sa.or_(
                columns.no_results,
                columns.passages == 0,
                InsightsRepository._weak_score(columns.best_score),
            ),
        )
        return searched, missed

    @staticmethod
    def _weak_score(best_score: Any) -> sa.ColumnElement[bool]:
        return sa.and_(best_score.is_not(None), best_score < KNOWLEDGE_SCORE_FLOOR)

    @staticmethod
    def _question_groups(
        scoped: sa.Subquery, *, include_followups: bool, sample_sessions: int
    ) -> sa.Select[Any]:
        """Exact-text groups of ``scoped``'s questions after normalisation,
        commonest first: the grouping every common-questions read shares.

        Columns: ``occurrences``, ``conversations``, ``display_text`` (one of
        the group's questions), ``sample_session_ids`` and ``total``, the
        number of questions the shares are relative to.
        """
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
        return stmt.group_by(normalized).order_by(
            sa.desc("occurrences"), sa.asc("display_text")
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
        stmt = (
            self._question_groups(
                scoped,
                include_followups=include_followups,
                sample_sessions=sample_sessions,
            )
            .add_columns(
                sa.func.array_agg(scoped.c.id, type_=sa.ARRAY(sa.UUID())).label(
                    "question_ids"
                )
            )
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

    async def question_groups(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
        knowledge: KnowledgeSetup,
        n: int,
        include_followups: bool,
    ) -> tuple[list[QuestionGroupRow], int]:
        """The commonest question groups (as :meth:`top_questions` groups
        them) with how their answers fared: answers that say they cannot
        answer, answer ratings, and knowledge searched and missed as the
        summary judges them (None without knowledge). Returns ``(rows,
        total)`` where ``total`` is the number of questions the shares are
        relative to."""
        base = self._with_answer_rating(self._scoped_questions(scope, window, source))
        if knowledge.has_knowledge:
            base = self._with_knowledge_signals(base)
        scoped = base.subquery("scoped")
        s = scoped.c
        columns: list[sa.ColumnElement[Any]] = [
            sa.func.count()
            .filter(s.answer.op("~*")(NOT_KNOWING_REGEX))
            .label("unanswered"),
            sa.func.count().filter(s.rating == 1).label("answers_positive"),
            sa.func.count().filter(s.rating == -1).label("answers_negative"),
        ]
        if knowledge.has_knowledge:
            searched, missed = self._knowledge_verdict(s, knowledge)
            columns += [
                sa.func.count().filter(searched).label("knowledge_searched"),
                sa.func.count().filter(missed).label("knowledge_missed"),
            ]
        stmt = (
            self._question_groups(
                scoped, include_followups=include_followups, sample_sessions=1
            )
            .add_columns(*columns)
            .limit(n)
        )
        rows = (await self.session.execute(stmt)).all()
        total = int(rows[0].total) if rows else 0
        return (
            [
                QuestionGroupRow(
                    display_text=row.display_text,
                    occurrences=int(row.occurrences),
                    conversations=int(row.conversations),
                    sample_session_id=row.sample_session_ids[0],
                    unanswered=int(row.unanswered),
                    answers_positive=int(row.answers_positive),
                    answers_negative=int(row.answers_negative),
                    knowledge=(
                        KnowledgeUse(
                            searched=int(row.knowledge_searched),
                            missed=int(row.knowledge_missed),
                        )
                        if knowledge.has_knowledge
                        else None
                    ),
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

        cited = self._answer_passages()
        turns_stmt = (
            sa.select(
                Questions.id,
                Questions.created_at,
                Questions.question,
                Questions.answer,
                Questions.tool_calls,
                cited.c.passages.label("cited_passages"),
                cited.c.best_score,
            )
            .select_from(Questions)
            .join(cited, sa.true())
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
        source: SessionSource | None = None,
    ) -> tuple[list[UnansweredRow], int]:
        """Turns whose answer admits not knowing, with the matched phrase,
        newest first."""
        scoped = self._with_answer_rating(
            self._scoped_questions(scope, window, source)
        ).subquery("scoped")
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
            scoped.c.source,
            scoped.c.rating,
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
                    source=cast(SessionSource, row.source),
                    rating=row.rating,
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
        source: SessionSource | None = None,
        absolute: KnowledgeSetup | None = None,
    ) -> tuple[list[NoKnowledgeRow], int, float | None]:
        """Turns answered without a usable knowledge hit, newest first.

        Three signals, weakest last: the knowledge tool reported no results;
        the answer cited no knowledge at all; or its best citation score is in
        the window's weakest quartile (relative, because score scales differ
        per embedding model) or below :data:`KNOWLEDGE_SCORE_FLOOR`. Passages
        count whether they were injected or fetched through the knowledge
        tool. Returns ``(rows, total, window median score)``.

        With ``absolute`` the rows are exactly the answers the summary counts
        as missed with that knowledge setup: absolute signals only, among the
        answers that searched (:meth:`_knowledge_verdict`), and no median.
        """
        base = self._with_answer_rating(self._scoped_questions(scope, window, source))
        scored = self._with_knowledge_signals(base).subquery("scored")
        s = scored.c
        uncited = s.passages == 0
        median: float | None = None
        if absolute is None:
            quartile, median = (
                await self.session.execute(
                    sa.select(
                        sa.func.percentile_cont(0.25).within_group(s.best_score),
                        sa.func.percentile_cont(0.5).within_group(s.best_score),
                    ).where(s.best_score.isnot(None))
                )
            ).one()
            weak = sa.and_(
                s.best_score.isnot(None),
                sa.or_(
                    s.best_score < KNOWLEDGE_SCORE_FLOOR,
                    s.best_score <= quartile if quartile is not None else sa.false(),
                ),
            )
            flagged = sa.or_(s.no_results, uncited, weak)
        else:
            weak = self._weak_score(s.best_score)
            _, flagged = self._knowledge_verdict(s, absolute)
        reason = sa.case(
            (s.no_results, sa.literal("no_results")),
            (uncited, sa.literal("uncited")),
            (weak, sa.literal("weak_score")),
        ).label("reason")
        base = sa.select(
            s.id,
            s.created_at,
            s.session_id,
            s.question,
            s.best_score,
            reason,
            s.source,
            s.rating,
        ).where(flagged)
        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        rows = (
            await self.session.execute(
                base.order_by(s.created_at.desc(), s.id.desc())
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
                    reason=cast(MissReason, row.reason),
                    best_score=float(row.best_score)
                    if row.best_score is not None
                    else None,
                    source=cast(SessionSource, row.source),
                    rating=row.rating,
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
        source: SessionSource | None = None,
    ) -> tuple[list[RephrasingRow], int]:
        """Conversations where the user seems to have asked the same thing
        again: at least three questions with a textually similar consecutive
        pair first, then long conversations without one."""
        scoped = self._scoped_questions(scope, window, source).subquery("scoped")
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
            scoped.c.source,
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
                # One source per conversation.
                sa.func.min(ordered.c.source).label("source"),
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
                    source=cast(SessionSource, row.source),
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
        stmt = sa.select(
            Assistants.id,
            Assistants.knowledge_mode,
            has_knowledge.label("has_knowledge"),
        ).where(Assistants.id.in_(self._answering_assistants(scope)))
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
        absolute signals only (:meth:`_knowledge_verdict`). Without knowledge
        the figure is None.
        """
        base = (
            self._scoped_questions(scope, window, source)
            .add_columns(
                self._is_only_question_expr().label("only_question"),
                Sessions.feedback_value.label("conversation_rating"),
                Sessions.feedback_text.label("conversation_comment"),
                QuestionFeedback.value.label("answer_rating"),
                QuestionFeedback.text.label("answer_comment"),
            )
            .outerjoin(QuestionFeedback, QuestionFeedback.question_id == Questions.id)
        )
        if knowledge.has_knowledge:
            base = self._with_knowledge_signals(base)
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
        has_comment = _has_text(s.answer_comment)
        conversation_has_comment = _has_text(s.conversation_comment)
        conversation_count = sa.func.count(sa.distinct(s.session_id))
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
            sa.func.count()
            .filter(s.answer_rating == -1, has_comment)
            .label("answers_negative_with_comment"),
            conversation_count.filter(s.conversation_rating == 1).label(
                "conversations_positive"
            ),
            conversation_count.filter(s.conversation_rating == -1).label(
                "conversations_negative"
            ),
            conversation_count.filter(
                s.conversation_rating.is_not(None), conversation_has_comment
            ).label("conversations_with_comment"),
            conversation_count.filter(
                s.conversation_rating == -1, conversation_has_comment
            ).label("conversations_negative_with_comment"),
        ]
        if knowledge.has_knowledge:
            searched, missed = self._knowledge_verdict(s, knowledge)
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
            answers_negative_with_comment=int(row.answers_negative_with_comment),
            conversations_positive=int(row.conversations_positive),
            conversations_negative=int(row.conversations_negative),
            conversations_with_comment=int(row.conversations_with_comment),
            conversations_negative_with_comment=int(
                row.conversations_negative_with_comment
            ),
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

    def _answering_assistants(self, scope: InsightScope) -> sa.Select[Any]:
        """The ids of the assistants that answer for the target now: the
        assistant, or a group chat's members, in the scope's tenant."""
        stmt = (
            sa.select(Assistants.id)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Spaces.tenant_id == scope.tenant_id)
            # Never correlated to an enclosing read of assistants.
            .correlate(None)
        )
        if scope.kind == "assistant":
            return stmt.where(Assistants.id == scope.target_id)
        return stmt.where(
            Assistants.id.in_(
                sa.select(GroupChatsAssistantsMapping.assistant_id).where(
                    GroupChatsAssistantsMapping.group_chat_id == scope.target_id
                )
            )
        )

    async def knowledge_citations(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
    ) -> KnowledgeCitations:
        """Per knowledge source, the answers of the window that cited at least
        one passage from it, injected or fetched through the knowledge tool,
        and the attached sources no answer cited.

        A source is the collection, website or integration knowledge a cited
        passage's info blob belongs to. A refreshed document keeps its earlier
        versions (superseded, with their source), so its citations stay
        counted; a citation goes with its document when the document itself
        is removed, and then no longer counts.
        """
        passages = self._cited_passages().lateral("passages")
        kind = sa.case(
            (InfoBlobs.group_id.is_not(None), sa.literal("collection")),
            (InfoBlobs.website_id.is_not(None), sa.literal("website")),
            (
                InfoBlobs.integration_knowledge_id.is_not(None),
                sa.literal("integration_knowledge"),
            ),
        )
        source_id = sa.func.coalesce(
            InfoBlobs.group_id, InfoBlobs.website_id, InfoBlobs.integration_knowledge_id
        )
        cited = (
            sa.select(
                Questions.id.label("question_id"),
                kind.label("kind"),
                source_id.label("source_id"),
            )
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .outerjoin(passages, sa.true())
            .outerjoin(
                InfoBlobs,
                sa.and_(
                    InfoBlobs.id == passages.c.info_blob_id,
                    InfoBlobs.tenant_id == scope.tenant_id,
                ),
            )
            .where(*self._in_scope(scope, window, source))
            .subquery("cited")
        )
        c = cited.c
        # One row per cited source, and one for the whole window.
        counts = (
            sa.select(
                sa.func.grouping(c.kind, c.source_id).label("grouping"),
                c.kind,
                c.source_id,
                sa.func.count(sa.distinct(c.question_id)).label("answers"),
                sa.func.count(sa.distinct(c.question_id))
                .filter(c.source_id.is_not(None))
                .label("citing_answers"),
            )
            .group_by(
                sa.func.grouping_sets(sa.tuple_(c.kind, c.source_id), sa.tuple_())
            )
            .subquery("counts")
        )
        rows = (
            await self.session.execute(
                self._with_source_names(counts).where(
                    sa.or_(counts.c.grouping != 0, counts.c.source_id.is_not(None))
                )
            )
        ).all()
        attached = await self._attached_knowledge(scope)
        attached_ids = {row.id for row in attached}
        totals = next((row for row in rows if row.grouping != 0), None)
        cited_rows = sorted(
            (
                KnowledgeSourceRow(
                    kind=cast(KnowledgeSourceKind, row.kind),
                    id=row.source_id,
                    name=row.name or "",
                    answers=int(row.answers),
                    attached=row.source_id in attached_ids,
                )
                for row in rows
                if row.grouping == 0
            ),
            key=lambda row: (-row.answers, row.name.lower(), str(row.id)),
        )
        cited_ids = {row.id for row in cited_rows}
        return KnowledgeCitations(
            answers=int(totals.answers) if totals is not None else 0,
            citing_answers=int(totals.citing_answers) if totals is not None else 0,
            cited=cited_rows,
            unused=[row for row in attached if row.id not in cited_ids],
        )

    @staticmethod
    def _with_source_names(sources: sa.Subquery) -> sa.Select[Any]:
        """Every column of ``sources`` (a ``kind`` and a ``source_id`` among
        them) and the source's display name as ``name``; a website without a
        name shows its address."""
        kind, source_id = sources.c.kind, sources.c.source_id
        return (
            sa.select(
                sources,
                sa.func.coalesce(
                    CollectionsTable.name,
                    Websites.name,
                    Websites.url,
                    IntegrationKnowledge.name,
                    IntegrationKnowledge.original_name,
                ).label("name"),
            )
            .select_from(sources)
            .outerjoin(
                CollectionsTable,
                sa.and_(kind == "collection", CollectionsTable.id == source_id),
            )
            .outerjoin(Websites, sa.and_(kind == "website", Websites.id == source_id))
            .outerjoin(
                IntegrationKnowledge,
                sa.and_(
                    kind == "integration_knowledge",
                    IntegrationKnowledge.id == source_id,
                ),
            )
        )

    async def _attached_knowledge(
        self, scope: InsightScope
    ) -> list[KnowledgeSourceRow]:
        """The knowledge sources attached to the target's answering
        assistants now, by name; a group chat's are its members' together."""
        assistants = self._answering_assistants(scope)
        attached = sa.union(
            sa.select(
                sa.literal("collection").label("kind"),
                AssistantsGroups.group_id.label("source_id"),
            ).where(AssistantsGroups.assistant_id.in_(assistants)),
            sa.select(
                sa.literal("website").label("kind"),
                AssistantsWebsites.website_id.label("source_id"),
            ).where(AssistantsWebsites.assistant_id.in_(assistants)),
            sa.select(
                sa.literal("integration_knowledge").label("kind"),
                AssistantIntegrationKnowledge.integration_knowledge_id.label(
                    "source_id"
                ),
            ).where(AssistantIntegrationKnowledge.assistant_id.in_(assistants)),
        ).subquery("attached")
        rows = (await self.session.execute(self._with_source_names(attached))).all()
        return sorted(
            (
                KnowledgeSourceRow(
                    kind=cast(KnowledgeSourceKind, row.kind),
                    id=row.source_id,
                    name=row.name or "",
                    answers=0,
                    attached=True,
                )
                for row in rows
            ),
            key=lambda row: (row.name.lower(), str(row.id)),
        )

    async def tool_use(
        self,
        scope: InsightScope,
        window: InsightWindow,
        *,
        source: SessionSource | None,
    ) -> list[ToolUseRow]:
        """Tool calls of the window's answers, most called first.

        A capability's calls (web search, image generation and the other
        purposes) are one row whichever server backed them; other calls are
        one row per server and tool, with the stored display title. A call
        failed when its result status says so, and was denied when it was not
        approved (by the person or by the approval timeout). Calls of Eneo's
        own knowledge server are left out (the knowledge figures cover them),
        and so are Skill activations, which are steps of the answer.
        """
        call = self._turn_calls(Questions.tool_calls)
        value = call.c.value

        def field(name: str) -> sa.ColumnElement[Any]:
            return value.op("->>")(name)

        purpose = field("purpose")
        knowledge_server = sa.and_(
            field("server_name") == KNOWLEDGE_SERVER,
            # Rows from before is_internal existed fall back to the name.
            sa.func.coalesce(field("is_internal"), "true") != "false",
        )
        calls = (
            sa.select(
                purpose.label("purpose"),
                sa.case((purpose.is_(None), field("server_name"))).label("server_name"),
                sa.case((purpose.is_(None), field("tool_name"))).label("tool_name"),
                field("title").label("title"),
                (field("result_status") == "failed").label("failed"),
                (field("approved") == "false").label("denied"),
            )
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(call, sa.true())
            .where(
                *self._in_scope(scope, window, source),
                sa.not_(knowledge_server),
                sa.func.coalesce(field("mcp_tool_name"), "") != SKILL_ACTIVATION_TOOL,
            )
            .subquery("calls")
        )
        c = calls.c
        rows = (
            await self.session.execute(
                sa.select(
                    c.purpose,
                    c.server_name,
                    c.tool_name,
                    sa.func.max(c.title).label("title"),
                    sa.func.count().label("calls"),
                    sa.func.count().filter(c.failed).label("failed"),
                    sa.func.count().filter(c.denied).label("denied"),
                )
                .group_by(c.purpose, c.server_name, c.tool_name)
                .order_by(
                    sa.desc("calls"),
                    c.purpose.asc().nulls_last(),
                    c.server_name.asc(),
                    c.tool_name.asc(),
                )
            )
        ).all()
        return [
            ToolUseRow(
                purpose=row.purpose,
                server_name=row.server_name,
                tool_name=row.tool_name,
                title=row.title if row.purpose is None else None,
                calls=int(row.calls),
                failed=int(row.failed),
                denied=int(row.denied),
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
        offset: int = 0,
    ) -> tuple[list[RatingRow], int, bool]:
        """Answer and conversation ratings, newest rating first. Returns
        ``(page, total, has_more)``.

        An answer rating belongs to the window of its question; a
        conversation rating to every window the conversation had a question
        in, as the figures count it. ``after`` is the ``(rated_at, key)`` of
        the previous page's last row; ``offset`` skips rows after it.
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
                Questions.id.label("quoted_question_id"),
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
            sa.select(Questions.id, Questions.question)
            .where(Questions.session_id == Sessions.id)
            .order_by(Questions.created_at.asc(), Questions.id.asc())
            .limit(1)
            .correlate(Sessions)
            .lateral("first_question")
        )
        conversations = (
            sa.select(
                sa.literal("conversation", sa.String).label("kind"),
                Sessions.feedback_value.label("value"),
                Sessions.feedback_text.label("comment"),
                first_question.c.question.label("question"),
                sa.cast(sa.null(), sa.Uuid()).label("question_id"),
                Sessions.id.label("session_id"),
                session_source().label("source"),
                # The stored feedback time: a widget vote without a comment
                # keeps the time of the comment before it, or of the
                # conversation's start.
                Sessions.feedback_set_at.label("rated_at"),
                Sessions.id.label("key"),
                first_question.c.id.label("quoted_question_id"),
            )
            .select_from(Sessions)
            .join(first_question, sa.true())
            .where(Sessions.feedback_value.is_not(None), Sessions.id.in_(active))
        )
        ratings = sa.union_all(answers, conversations).subquery("ratings")
        r = ratings.c

        filters: list[sa.ColumnElement[bool]] = []
        if value is not None:
            filters.append(r.value == value)
        if has_comment is not None:
            commented = _has_text(r.comment)
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
        page = (
            page.order_by(r.rated_at.desc(), r.key.desc())
            .offset(offset)
            .limit(limit + 1)
        )
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
                    quoted_question_id=row.quoted_question_id,
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
    ) -> tuple[list[TargetRow], int, TargetTotals]:
        """Every assistant people see and every group chat of the tenant,
        with its usage in the window (and the previous window), in one
        statement. Returns ``(page, total, totals)``: the totals sum the usage
        of every target that matches, not only the page's.

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
        # The usage of every matching target, summed before the page is cut.
        summed_columns: list[sa.ColumnElement[int]] = [lc[c.name] for c in figures]
        totals = sa.select(
            sa.func.count().label("total"),
            *(
                sa.func.coalesce(sa.func.sum(column), 0).label(f"all_{column.name}")
                for column in summed_columns
            ),
        ).select_from(listed)
        totals_sq = totals.subquery("totals")
        # One row even for an empty page, so the totals always come back.
        stmt = (
            sa.select(totals_sq, page).select_from(totals_sq).outerjoin(page, sa.true())
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            none = TargetUsage(SourceCounts(0, 0, 0, 0), 0)
            return [], 0, TargetTotals(none, none)
        first = rows[0]
        summed = TargetTotals(
            usage=TargetUsage(
                conversations=_source_counts(first, "all_conversations"),
                questions=int(first.all_questions),
            ),
            previous=TargetUsage(
                conversations=_source_counts(first, "all_previous_conversations"),
                questions=int(first.all_previous_questions),
            ),
        )
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
            int(first.total),
            summed,
        )
