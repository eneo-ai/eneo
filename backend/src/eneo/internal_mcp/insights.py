# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server exposing insights analysis tools.

The tools read the conversations users had with one target assistant or
group chat, for an operator analysing how it is used. The bearer token's
``insight_target_type`` / ``insight_target_id`` claims fix the target and
its ``session_id`` claim names the insights conversation the tools answer
in; every call re-checks the operator's insight access for the target. See
:mod:`eneo.internal_mcp.foundation` for the hosting and authentication model
shared by all internal servers.

All time arguments are ISO-8601 with a UTC offset plus an IANA ``timezone``
that fixes calendar boundaries and displayed times, so "yesterday" means the
operator's yesterday. Every tool self-caps its output with
:func:`default_page_cap` and continues via ``offset``.

Every tool that returns text from the analysed conversations (questions,
answers, rating comments) knows which questions that text comes from
(:class:`ToolPage`) and returns it through :func:`_release_page`, which
records the insights conversation as a copy of those questions first
(:mod:`eneo.data_retention.derivations`): the analysis is then removed with
any of them. Tools that return counts and configured names only register
nothing. The results are plain text, never structured content, so a call's
result reaches the operator's browser only through the tool-result endpoint.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from eneo.analysis.insight_scope import (
    InsightScope,
    InsightTargetKind,
    InsightWindow,
    MissReason,
)
from eneo.analysis.insights_repo import (
    Granularity,
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
    UnansweredRow,
    UsageSummary,
)
from eneo.data_retention.derivations import (
    DerivationRegistrationError,
    register_derivations,
)
from eneo.internal_mcp.constants import INSIGHTS_SERVER_NAME
from eneo.internal_mcp.foundation import (
    account_tool_container,
    bearer_from_ctx,
    build_ephemeral_server,
    default_page_cap,
    fit_lines,
    session_id_from_token,
    verified_claims,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)

# Longest window a single call may cover. Longer spans are almost always a
# mistaken argument; the model is told to narrow or split the range.
MAX_WINDOW_DAYS = 400
# Most rows a usage breakdown returns before the model is asked for a
# coarser granularity, keeping one call well inside the page cap.
MAX_BUCKETS = 120
LIST_LIMIT_CEILING = 200
TOP_N_CEILING = 50
# Rows fetched per gap-signal page before the character cap trims further.
GAP_PAGE_ROWS = 50
# Returned whenever a session id names nothing in the target's conversations.
# Missing, hidden and out-of-scope are indistinguishable on purpose, so this
# is a constant, never interpolated with what was asked for.
CONVERSATION_NOT_FOUND_MESSAGE = (
    "No conversation with that session id among this target's conversations. "
    "Use the session ids that list_questions, top_questions or "
    "search_questions return."
)
# Returned instead of a page whose sources could not be recorded: none of
# the page's text may leave the tool then.
SOURCES_NOT_RECORDED_MESSAGE = (
    "This result could not be returned: the questions it quotes could not be "
    "recorded as sources of this analysis. Try the call again."
)
# Question text shown per line; long messages are cut so one page still
# lists many questions. read_conversation shows full text.
QUESTION_PREVIEW_CHARS = 300
_MISS_REASONS: dict[MissReason, str] = {
    "no_results": "knowledge search returned no results",
    "uncited": "answer cited no knowledge",
    "weak_score": "weak best citation score",
}
_SOURCE_NOUNS = {
    "collection": "collection",
    "website": "website",
    "integration_knowledge": "integration knowledge",
}

# Every tool only reads; none is ever asked about before it runs.
_READS = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP(
    name="Eneo Insights",
    stateless_http=True,
    instructions=(
        "Analysis tools over the conversations users had with one Eneo "
        "assistant or group chat. Scope is fixed by the access token; tools "
        "take no target id. Always call a tool before answering, page through "
        "truncated output as far as the answer needs and say how much was "
        "read, and cite conversations by session id."
    ),
)


class InsightToolContext(NamedTuple):
    """User-bound DI container, identity and scope for one insights tool call."""

    container: Any
    user: Any
    scope: InsightScope
    target_label: str
    # The insights conversation the tools answer in: the copy that what they
    # return from other conversations ends up in.
    session_id: UUID
    # Whether the target can cite knowledge at all (any member assistant for
    # a group chat); the no-knowledge gap signal is meaningless otherwise.
    has_knowledge: bool = False


class ToolPage(NamedTuple):
    """A tool's text and the questions whose text it prints."""

    text: str
    question_ids: list[UUID]


def insight_target_from_token(token: str) -> tuple[InsightTargetKind, UUID]:
    """The analysed target this token was minted for."""
    claims = verified_claims(token)
    kind = claims.get("insight_target_type")
    raw = claims.get("insight_target_id")
    if kind not in ("assistant", "group_chat") or not raw:
        raise ValueError("Access token is not scoped to an insights target.")
    return kind, UUID(str(raw))


def insight_session_from_token(token: str) -> UUID:
    """The insights conversation this token was minted for."""
    session_id = session_id_from_token(token)
    if session_id is None:
        raise ValueError("Access token is not scoped to an insights conversation.")
    return session_id


def target_label(kind: InsightTargetKind, name: str) -> str:
    noun = "assistant" if kind == "assistant" else "group chat"
    return f"{noun} '{name}'"


@asynccontextmanager
async def insight_tool_context(ctx: Context) -> AsyncGenerator[InsightToolContext]:
    """Bootstrap a user-bound container and verify insight access.

    Access is re-checked on every call through the same decision as the
    insights chat's endpoints (``AnalysisService.assert_insight_access``), so
    a token minted before insights were disabled for the target, or before
    the operator lost access, stops working immediately.
    """
    token = bearer_from_ctx(ctx)
    kind, target_id = insight_target_from_token(token)
    session_id = insight_session_from_token(token)
    async with account_tool_container(token) as (container, user):
        analysis_service = container.analysis_service()
        if kind == "assistant":
            target, _space = await analysis_service.assert_insight_access(
                assistant_id=target_id
            )
        else:
            target, _space = await analysis_service.assert_insight_access(
                group_chat_id=target_id
            )
        scope = InsightScope(kind=kind, target_id=target_id, tenant_id=user.tenant_id)
        yield InsightToolContext(
            container=container,
            user=user,
            scope=scope,
            target_label=target_label(kind, target.name),
            session_id=session_id,
            has_knowledge=_target_has_knowledge(target),
        )


def _target_has_knowledge(target: Any) -> bool:
    # Imported here: the assistant domain imports the internal servers.
    from eneo.assistants.assistant import Assistant

    if isinstance(target, Assistant):
        return target.has_knowledge()
    return any(member.assistant.has_knowledge() for member in target.assistants)


async def _release_page(copy_session_id: UUID, page: ToolPage) -> str:
    """The page's text, once the insights conversation is recorded as a copy
    of every question the page prints.

    Every tool that returns text from the analysed conversations returns it
    through here, so the analysis is removed with any of those questions.
    Tools call it after their own transaction closed: the registration
    commits in a transaction of its own, and one call never holds two pooled
    connections at once. The conversation's session was committed with its
    first question before the token naming it was minted. When the
    registration cannot be confirmed, none of the page's text is returned.
    """
    try:
        await register_derivations(
            copy_session_id=copy_session_id,
            source_question_ids=page.question_ids,
        )
    except DerivationRegistrationError:
        logger.warning(
            "[Insights] page withheld, sources not recorded session=%s questions=%d",
            copy_session_id,
            len(set(page.question_ids)),
            exc_info=True,
        )
        return SOURCES_NOT_RECORDED_MESSAGE
    return page.text


# --------------------------------------------------------------------------- #
# Argument parsing and formatting
# --------------------------------------------------------------------------- #
def _parse_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} must be an ISO-8601 datetime with a UTC offset, "
            f"e.g. 2026-09-07T00:00:00+02:00 (got {value!r})."
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"{name} must include a UTC offset, e.g. 2026-09-07T00:00:00+02:00 "
            f"(got {value!r})."
        )
    return parsed


def _parse_timezone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError(
            f"Unknown timezone {timezone!r}. Pass an IANA name such as "
            "Europe/Stockholm or UTC."
        )


def _parse_window(start: str, end: str, timezone: str) -> InsightWindow:
    """Validate the window before any SQL runs.

    Rejects naive datetimes (a bare local time is ambiguous), empty or
    reversed windows, and spans beyond :data:`MAX_WINDOW_DAYS`.
    """
    _parse_timezone(timezone)
    start_dt = _parse_datetime(start, "start")
    end_dt = _parse_datetime(end, "end")
    if end_dt <= start_dt:
        raise ValueError("end must be after start (end is exclusive).")
    if end_dt - start_dt > timedelta(days=MAX_WINDOW_DAYS):
        raise ValueError(
            f"The window spans more than {MAX_WINDOW_DAYS} days; narrow it or "
            "split it into several calls."
        )
    return InsightWindow(start=start_dt, end=end_dt, timezone=timezone)


def _bucket_count(window: InsightWindow, granularity: Granularity) -> int:
    """Upper bound on rows a breakdown produces, to refuse before querying."""
    tz = ZoneInfo(window.timezone)
    start = window.start.astimezone(tz)
    end = window.end.astimezone(tz)
    if granularity == "month":
        return (end.year - start.year) * 12 + (end.month - start.month) + 1
    days = (end.date() - start.date()).days + 1
    return days if granularity == "day" else days // 7 + 1


def _local(moment: datetime, timezone: str) -> datetime:
    return moment.astimezone(ZoneInfo(timezone))


def _format_window(window: InsightWindow) -> str:
    start = _local(window.start, window.timezone).isoformat(timespec="minutes")
    end = _local(window.end, window.timezone).isoformat(timespec="minutes")
    return f"{start} to {end} ({window.timezone})"


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= QUESTION_PREVIEW_CHARS:
        return flat
    return flat[:QUESTION_PREVIEW_CHARS] + "…"


def _usage_summary_text(
    summary: UsageSummary,
    window: InsightWindow,
    granularity: Granularity,
    label: str,
) -> str:
    if summary.questions == 0:
        return f"No questions for {label} in {_format_window(window)}."
    followup_share = 100 * summary.followups / summary.questions
    lines = [
        f"Usage for {label}, {_format_window(window)}:",
        f"- Conversations: {summary.conversations}",
        (
            f"- Questions: {summary.questions} (follow-ups: {summary.followups}, "
            f"{followup_share:.1f}%)"
        ),
        (
            f"- Distinct users: {summary.users} (API-key conversations: "
            f"{summary.api_key_conversations}, widget conversations: "
            f"{summary.widget_conversations})"
        ),
        f"Per {granularity} (local time, periods with no activity omitted):",
    ]
    date_format = "%Y-%m" if granularity == "month" else "%Y-%m-%d"
    for bucket in summary.buckets:
        lines.append(
            f"{bucket.bucket_start.strftime(date_format)} | "
            f"conversations={bucket.conversations} | questions={bucket.questions} | "
            f"users={bucket.users}"
        )
    return "\n".join(lines)


def _question_lines(rows: list[QuestionRow], timezone: str) -> list[str]:
    return [
        f"{_local(row.created_at, timezone).strftime('%Y-%m-%d %H:%M')} | "
        f"session_id={row.session_id} | {_preview(row.question)}"
        for row in rows
    ]


def _list_questions_text(
    rows: list[QuestionRow],
    *,
    total: int,
    offset: int,
    include_followups: bool,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> ToolPage:
    if total == 0:
        return ToolPage(f"No questions for {label} in {_format_window(window)}.", [])
    if not rows:
        return ToolPage(f"Offset {offset} is past the end ({total} questions).", [])
    kept = fit_lines(_question_lines(rows, window.timezone), page_cap)
    shown_to = offset + len(kept)
    scope_note = "all questions" if include_followups else "opening questions only"
    header = (
        f"Questions {offset + 1}-{shown_to} of {total} for {label}, newest first "
        f"(local time {window.timezone}; {scope_note}):"
    )
    body = "\n".join(kept)
    if shown_to < total:
        body += (
            f"\n\nShowing {offset + 1}-{shown_to} of {total}. Call list_questions "
            f"again with offset={shown_to} for the next part before summarising."
        )
    return ToolPage(f"{header}\n{body}", [row.question_id for row in rows[: len(kept)]])


def _top_questions_text(
    rows: list[TopQuestionRow],
    *,
    total: int,
    include_followups: bool,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> ToolPage:
    if total == 0 or not rows:
        return ToolPage(f"No questions for {label} in {_format_window(window)}.", [])
    lines = []
    for rank, row in enumerate(rows, start=1):
        share = 100 * row.occurrences / total
        sessions = ", ".join(str(session_id) for session_id in row.sample_session_ids)
        lines.append(
            f"{rank}. {row.occurrences}x ({share:.1f}%, {row.conversations} conversations) "
            f'"{_preview(row.display_text)}" sessions: {sessions}'
        )
    kept = fit_lines(lines, page_cap)
    scope_note = "all questions" if include_followups else "opening questions only"
    header = (
        f"Top {len(kept)} exact-text question groups of {total} questions for "
        f"{label}, {_format_window(window)} ({scope_note}; whitespace, case and "
        "trailing ?!. ignored):"
    )
    footer = (
        "Different wordings of the same question are separate rows: merge "
        "near-duplicates yourself and mark merged counts as approximate. A "
        'row with count 1 is not "most common".'
    )
    return ToolPage(
        f"{header}\n" + "\n".join(kept) + f"\n\n{footer}",
        [question_id for row in rows[: len(kept)] for question_id in row.question_ids],
    )


def _paged(
    lines: list[str],
    *,
    header: str,
    offset: int,
    total: int,
    tool_name: str,
    page_cap: int,
) -> tuple[str, int]:
    """One page of ``lines`` under ``header``, and how many lines it kept."""
    kept = fit_lines(lines, page_cap)
    shown_to = offset + len(kept)
    body = "\n".join(kept)
    if shown_to < total:
        body += (
            f"\n\nShowing {offset + 1}-{shown_to} of {total}. Call {tool_name} "
            f"again with offset={shown_to} for the next part before summarising."
        )
    return f"{header}\n{body}", len(kept)


def _search_text(
    hits: list[SearchHit],
    *,
    query: str,
    total: int,
    offset: int,
    include_answers: bool,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> ToolPage:
    if total == 0:
        return ToolPage(
            f"No questions matching {query!r} for {label} in "
            f"{_format_window(window)}. Try a shorter or differently spelled "
            "phrase; matching is by substring and trigram similarity.",
            [],
        )
    if not hits:
        return ToolPage(f"Offset {offset} is past the end ({total} matches).", [])
    lines = []
    for hit in hits:
        kind = "exact" if hit.exact else "similar"
        line = (
            f"{_local(hit.created_at, window.timezone).strftime('%Y-%m-%d %H:%M')} | "
            f"session_id={hit.session_id} | {kind} | Q: {_preview(hit.question)}"
        )
        if include_answers:
            line += f" | A: {_preview(hit.answer)}"
        lines.append(line)
    text, kept = _paged(
        lines,
        header=(
            f"Questions {offset + 1}-{offset + len(hits)} of {total} matching "
            f"{query!r} for {label}, substring matches first (local time "
            f"{window.timezone}):"
        ),
        offset=offset,
        total=total,
        tool_name="search_questions",
        page_cap=page_cap,
    )
    return ToolPage(text, [hit.question_id for hit in hits[:kept]])


def _transcript_text(
    transcript: Transcript, *, offset: int, timezone: str, page_cap: int
) -> ToolPage:
    """One page of the full conversation, sliced by characters like a document.

    The page names the turns whose text it shows, in part or in full.
    """
    text = (
        f"Conversation session_id={transcript.session_id}, started "
        f"{_local(transcript.started_at, timezone).strftime('%Y-%m-%d %H:%M')} "
        f"({timezone}), {len(transcript.turns)} turns."
    )
    spans: list[tuple[int, int, UUID]] = []
    for number, turn in enumerate(transcript.turns, start=1):
        details = [f"cited passages: {turn.cited_passages}"]
        if turn.best_score is not None:
            details.append(f"best score: {turn.best_score:.2f}")
        if turn.tool_names:
            details.append("tools: " + ", ".join(turn.tool_names))
        part = (
            f"\n\n### Turn {number} "
            f"({_local(turn.created_at, timezone).strftime('%H:%M')})\n"
            f"User: {' '.join(turn.question.split())}\n"
            f"Assistant: {' '.join(turn.answer.split()) or '(no answer)'}\n"
            f"[{'; '.join(details)}]"
        )
        spans.append((len(text), len(text) + len(part), turn.question_id))
        text += part
    total = len(text)
    page = text[offset : offset + page_cap]
    if not page:
        return ToolPage(
            f"Offset {offset} is past the end of the conversation ({total} characters).",
            [],
        )
    end = offset + len(page)
    if end < total:
        page += (
            f"\n\nConversation truncated at character {end} of {total}. Call "
            f"read_conversation again with offset={end} for the next part."
        )
    return ToolPage(
        page,
        [
            question_id
            for start, stop, question_id in spans
            if start < end and stop > offset
        ],
    )


def _unanswered_lines(rows: list[UnansweredRow], timezone: str) -> list[str]:
    return [
        f"{_local(row.created_at, timezone).strftime('%Y-%m-%d %H:%M')} | "
        f"session_id={row.session_id} | Q: {_preview(row.question)} | "
        f'admits: "{" ".join(row.evidence.split())}"'
        for row in rows
    ]


def _no_knowledge_lines(rows: list[NoKnowledgeRow], timezone: str) -> list[str]:
    lines = []
    for row in rows:
        score = (
            f", best score {row.best_score:.2f}" if row.best_score is not None else ""
        )
        lines.append(
            f"{_local(row.created_at, timezone).strftime('%Y-%m-%d %H:%M')} | "
            f"session_id={row.session_id} | Q: {_preview(row.question)} | "
            f"{_MISS_REASONS[row.reason]}{score}"
        )
    return lines


def _rephrasing_lines(rows: list[RephrasingRow], timezone: str) -> list[str]:
    lines = []
    for row in rows:
        sequence = " -> ".join(f'"{_preview(q)[:120]}"' for q in row.questions)
        lines.append(
            f"{_local(row.started_at, timezone).strftime('%Y-%m-%d %H:%M')} | "
            f"session_id={row.session_id} | {len(row.questions)} questions, "
            f"{row.similar_pairs} similar consecutive pairs | {sequence}"
        )
    return lines


def _ratings_text(
    rows: list[RatingRow],
    *,
    total: int,
    offset: int,
    filter_note: str,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> ToolPage:
    """One page of ratings with their comments. Each line quotes one
    question: the rated answer's, or a conversation rating's first."""
    if total == 0:
        return ToolPage(
            f"No ratings ({filter_note}) for {label} in {_format_window(window)}.", []
        )
    if not rows:
        return ToolPage(f"Offset {offset} is past the end ({total} ratings).", [])
    lines = []
    for row in rows:
        verdict = "good" if row.value == 1 else "bad"
        rated = (
            f"answer rated {verdict} | Q: "
            if row.kind == "answer"
            else f"conversation rated {verdict} | first Q: "
        )
        comment = (
            f' | comment: "{_preview(row.comment)}"'
            if row.comment and row.comment.strip()
            else " | no comment"
        )
        lines.append(
            f"{_local(row.rated_at, window.timezone).strftime('%Y-%m-%d %H:%M')} | "
            f"session_id={row.session_id} | {rated}{_preview(row.question)}{comment}"
        )
    text, kept = _paged(
        lines,
        header=(
            f"Ratings {offset + 1}-{offset + len(rows)} of {total} ({filter_note}) "
            f"for {label}, newest rating first (local time {window.timezone}):"
        ),
        offset=offset,
        total=total,
        tool_name="list_ratings",
        page_cap=page_cap,
    )
    return ToolPage(text, [row.quoted_question_id for row in rows[:kept]])


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def _source_label(source: KnowledgeSourceRow) -> str:
    return f"{_SOURCE_NOUNS[source.kind]} '{source.name}'"


def _knowledge_use_text(
    citations: KnowledgeCitations,
    *,
    offset: int,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> str:
    """Counts and source names only, so the text names no question."""
    if not citations.cited and not citations.unused:
        return (
            f"No knowledge sources are attached to {label}, and no answer cited "
            f"any in {_format_window(window)}."
        )
    lines = [
        f"cited | {_source_label(source)} | {source.answers} answers "
        f"({_share(source.answers, citations.citing_answers)} of citing answers)"
        + ("" if source.attached else " | no longer attached")
        for source in citations.cited
    ] + [
        f"never cited | {_source_label(source)} | attached"
        for source in citations.unused
    ]
    header = (
        f"Knowledge use for {label}, {_format_window(window)}: {citations.answers} "
        f"answers, of which {citations.citing_answers} "
        f"({_share(citations.citing_answers, citations.answers)}) cited a passage "
        "from a knowledge source. Sources, most cited first, then attached "
        "sources no answer cited:"
    )
    if offset >= len(lines):
        return f"Offset {offset} is past the end ({len(lines)} sources)."
    text, _ = _paged(
        lines[offset:],
        header=header,
        offset=offset,
        total=len(lines),
        tool_name="knowledge_use",
        page_cap=page_cap,
    )
    return text


def _tool_label(row: ToolUseRow) -> str:
    if row.purpose is not None:
        return f"capability {row.purpose}"
    title = f' ("{row.title}")' if row.title else ""
    return f"server '{row.server_name}' tool '{row.tool_name}'{title}"


def _tool_use_text(
    rows: list[ToolUseRow],
    *,
    offset: int,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> str:
    """Counts and configured names only, so the text names no question."""
    if not rows:
        return f"No tool calls for {label} in {_format_window(window)}."
    if offset >= len(rows):
        return f"Offset {offset} is past the end ({len(rows)} tools)."
    lines = [
        f"{_tool_label(row)} | {row.calls} calls | {row.failed} failed "
        f"({_share(row.failed, row.calls)}) | {row.denied} denied"
        for row in rows[offset:]
    ]
    text, _ = _paged(
        lines,
        header=(
            f"Tool use for {label}, {_format_window(window)}, most called first "
            "(Eneo's own knowledge tools and Skill activations are left out):"
        ),
        offset=offset,
        total=len(rows),
        tool_name="tool_use",
        page_cap=page_cap,
    )
    return text


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool(title="Usage summary", annotations=_READS, structured_output=False)
async def usage_summary(
    ctx: Context,
    start: str,
    end: str,
    timezone: str = "UTC",
    granularity: Literal["day", "week", "month"] = "day",
) -> str:
    """Totals and a per-period breakdown of how the target was used in a window.

    Use this first for any question about volume, trend or audience: "how much
    was it used last week", "is usage growing", "how many people asked
    something", "which day was busiest". It is cheap; call it before the
    listing tools to size the data.

    start and end are ISO-8601 datetimes with a UTC offset; end is exclusive.
    timezone is the IANA zone (e.g. Europe/Stockholm) that fixes day, week and
    month boundaries and the displayed times, so pass the operator's zone.
    granularity picks the breakdown period; a window that would produce more
    than about 120 periods is refused, so use week or month for long windows.

    Counts: conversations are sessions with at least one question in the
    window; questions are all user messages in the window, of which
    follow-ups are those that were not the first in their conversation;
    distinct users exclude API-key and widget traffic, which is counted
    separately. Periods with no activity are omitted from the breakdown.

    It returns counts only, never the text of a question or answer, so it
    adds no source conversations to this analysis.
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    buckets = _bucket_count(window, granularity)
    if buckets > MAX_BUCKETS:
        return (
            f"That window spans about {buckets} {granularity}s, which is too many "
            "rows for one call. Call usage_summary again with a coarser "
            "granularity (week or month) or a shorter window."
        )
    async with insight_tool_context(ctx) as tool:
        summary = await tool.container.insights_repo().count_usage(
            tool.scope, window, granularity
        )
        label = tool.target_label
    logger.debug(
        "[Insights] usage_summary target=%s window=%s questions=%d",
        label,
        _format_window(window),
        summary.questions,
    )
    # Counts only: no text from the conversations, so no sources.
    return _usage_summary_text(summary, window, granularity, label)


@mcp.tool(title="List questions", annotations=_READS, structured_output=False)
async def list_questions(
    ctx: Context,
    start: str,
    end: str,
    include_followups: bool = False,
    offset: int = 0,
    limit: int = 50,
    timezone: str = "UTC",
) -> str:
    """Questions users asked in a window, newest first, with their conversation.

    Use this to read what people actually asked: to characterise topics,
    find examples, or answer "what did users ask about yesterday". Prefer
    top_questions for frequency questions and usage_summary for counts.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the displayed times. include_followups=False
    lists only each conversation's opening question, which is the best
    single line per conversation; set it to true to see every message.

    Output is one page of up to `limit` lines in the form
    `<local time> | session_id=<uuid> | <question, cut at 300 characters>`.
    When a continuation notice appears, call again with the given offset and
    read every page before summarising. Cite examples in the answer as
    (session <uuid>) so the operator can open the conversation.
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    limit = max(1, min(limit, LIST_LIMIT_CEILING))
    async with insight_tool_context(ctx) as tool:
        rows, total = await tool.container.insights_repo().list_questions(
            tool.scope,
            window,
            include_followups=include_followups,
            offset=offset,
            limit=limit,
        )
        page = _list_questions_text(
            rows,
            total=total,
            offset=offset,
            include_followups=include_followups,
            window=window,
            label=tool.target_label,
            page_cap=default_page_cap(),
        )
    logger.debug(
        "[Insights] list_questions offset=%d rows=%d total=%d",
        offset,
        len(rows),
        total,
    )
    return await _release_page(tool.session_id, page)


@mcp.tool(title="Top questions", annotations=_READS, structured_output=False)
async def top_questions(
    ctx: Context,
    start: str,
    end: str,
    n: int = 10,
    include_followups: bool = False,
    timezone: str = "UTC",
) -> str:
    """Most frequently asked questions in a window, grouped by exact text.

    Use this for "most common questions", "what do people ask most", "top 5
    topics" and similar. Grouping ignores whitespace, letter case and
    trailing ?!. but is otherwise exact, so different wordings of the same
    question are separate rows: merge near-duplicates yourself in the answer
    and mark merged counts as approximate ("about 12"). Never call a row
    with count 1 "most common"; with thin data say the data is thin.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive).
    include_followups=False groups only each conversation's opening question.
    Each row shows rank, count, share of all questions in the window,
    distinct conversations, the text, and up to three session ids to cite as
    (session <uuid>).
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    n = max(1, min(n, TOP_N_CEILING))
    async with insight_tool_context(ctx) as tool:
        rows, total = await tool.container.insights_repo().top_questions(
            tool.scope, window, n=n, include_followups=include_followups
        )
        page = _top_questions_text(
            rows,
            total=total,
            include_followups=include_followups,
            window=window,
            label=tool.target_label,
            page_cap=default_page_cap(),
        )
    logger.debug(
        "[Insights] top_questions n=%d groups=%d total=%d", n, len(rows), total
    )
    return await _release_page(tool.session_id, page)


@mcp.tool(title="Search questions", annotations=_READS, structured_output=False)
async def search_questions(
    ctx: Context,
    query: str,
    start: str,
    end: str,
    include_answers: bool = False,
    offset: int = 0,
    limit: int = 50,
    timezone: str = "UTC",
) -> str:
    """Find questions about a topic by text, in a window.

    Use this when the operator names a subject ("questions about parking",
    "did anyone ask about opening hours") or when you need examples of one
    topic. Matching is a case-insensitive substring match first, then
    trigram similarity for misspellings and inflections; results list
    substring matches first, newest first within each group. Keep the query
    to one or two key words in the language of the questions; a whole
    sentence rarely matches.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the displayed times. include_answers=true
    appends the start of each answer, useful to judge whether the assistant
    handled the topic well. Output is one page; when a continuation notice
    appears, call again with the given offset. Cite examples as
    (session <uuid>).
    """
    query = query.strip()
    if not query:
        return "query must not be empty."
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    limit = max(1, min(limit, LIST_LIMIT_CEILING))
    async with insight_tool_context(ctx) as tool:
        hits, total = await tool.container.insights_repo().search_questions(
            tool.scope, window, query=query, offset=offset, limit=limit
        )
        page = _search_text(
            hits,
            query=query,
            total=total,
            offset=offset,
            include_answers=include_answers,
            window=window,
            label=tool.target_label,
            page_cap=default_page_cap(),
        )
    logger.debug(
        "[Insights] search_questions offset=%d hits=%d total=%d",
        offset,
        len(hits),
        total,
    )
    return await _release_page(tool.session_id, page)


@mcp.tool(title="Read conversation", annotations=_READS, structured_output=False)
async def read_conversation(
    ctx: Context,
    session_id: str,
    offset: int = 0,
    timezone: str = "UTC",
) -> str:
    """The full transcript of one conversation, turn by turn.

    Use this to verify a signal before reporting it: what exactly was asked,
    how the assistant answered, and whether the answer cited knowledge
    (each turn ends with its cited passage count, best citation score and
    the tools it called). Pass a session id from another tool's output.

    Long conversations come in parts; when a truncation notice appears, call
    again with the given offset. timezone is the IANA zone for the displayed
    times.
    """
    try:
        wanted = UUID(session_id.strip())
    except (ValueError, AttributeError):
        return CONVERSATION_NOT_FOUND_MESSAGE
    try:
        _parse_timezone(timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    async with insight_tool_context(ctx) as tool:
        transcript = await tool.container.insights_repo().get_transcript(
            tool.scope, wanted
        )
        if transcript is None:
            logger.debug("[Insights] read_conversation miss")
            return CONVERSATION_NOT_FOUND_MESSAGE
        page = _transcript_text(
            transcript, offset=offset, timezone=timezone, page_cap=default_page_cap()
        )
    logger.debug(
        "[Insights] read_conversation turns=%d offset=%d",
        len(transcript.turns),
        offset,
    )
    return await _release_page(tool.session_id, page)


@mcp.tool(title="Find gaps", annotations=_READS, structured_output=False)
async def find_gaps(
    ctx: Context,
    start: str,
    end: str,
    signal: Literal["unanswered", "no_knowledge", "rephrasing", "all"] = "all",
    offset: int = 0,
    timezone: str = "UTC",
) -> str:
    """Conversations where the assistant probably fell short, by signal.

    Use this for "what could the assistant not answer", "where is knowledge
    missing", "what should we add", "were users frustrated". Each signal is
    a heuristic that yields candidates; verify the important ones with
    read_conversation before drawing conclusions, and say that the counts
    are indicative.

    Signals:
    - unanswered: the answer contains a phrase admitting it could not answer
      (in Swedish or English); the matched phrase is shown as evidence.
    - no_knowledge: the assistant has knowledge sources but this answer used
      none well: the knowledge search returned nothing, the answer cited no
      knowledge, or its best citation score is in the window's weakest
      quartile or below 0.2. Skipped when the target has no knowledge.
    - rephrasing: the user asked textually similar questions in a row, or
      kept asking within one conversation; the question sequence is shown
      for you to judge.
    - all: a short page of each signal in turn.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the displayed times. Page one signal at a
    time with offset when its continuation notice appears. Cite conversations
    as (session <uuid>).
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    page_cap = default_page_cap()
    sections: list[str] = []
    printed: list[UUID] = []
    async with insight_tool_context(ctx) as tool:
        repo = tool.container.insights_repo()
        label = tool.target_label
        signals = (
            ["unanswered", "no_knowledge", "rephrasing"]
            if signal == "all"
            else [signal]
        )
        # In "all" mode each signal gets a third of the page and its own
        # first page; page a single signal for the rest.
        per_signal_cap = page_cap // len(signals)
        limit = GAP_PAGE_ROWS if signal != "all" else 10
        for name in signals:
            if name == "unanswered":
                rows, total = await repo.find_unanswered(
                    tool.scope, window, offset=offset, limit=limit
                )
                header = (
                    f"Unanswered ({total} turns admit not knowing) for {label}, "
                    f"{_format_window(window)}:"
                )
                lines = _unanswered_lines(rows, window.timezone)
                sources = [[row.question_id] for row in rows]
            elif name == "no_knowledge":
                if not tool.has_knowledge:
                    sections.append(
                        f"No-knowledge signal skipped: {label} has no knowledge sources."
                    )
                    continue
                rows, total, median = await repo.find_no_knowledge(
                    tool.scope, window, offset=offset, limit=limit
                )
                median_note = (
                    f"window median best score {median:.2f}"
                    if median is not None
                    else "no citation scores in the window"
                )
                header = (
                    f"No knowledge used ({total} turns; {median_note}) for {label}, "
                    f"{_format_window(window)}:"
                )
                lines = _no_knowledge_lines(rows, window.timezone)
                sources = [[row.question_id] for row in rows]
            else:
                rows, total = await repo.find_rephrasing(
                    tool.scope, window, offset=offset, limit=limit
                )
                header = (
                    f"Rephrasing ({total} conversations) for {label}, "
                    f"{_format_window(window)}:"
                )
                lines = _rephrasing_lines(rows, window.timezone)
                sources = [row.question_ids for row in rows]
            if total == 0:
                sections.append(header + "\n(none)")
                continue
            if not rows:
                sections.append(
                    header + f"\nOffset {offset} is past the end ({total})."
                )
                continue
            text, kept = _paged(
                lines,
                header=header,
                offset=offset,
                total=total,
                tool_name=f'find_gaps with signal="{name}"',
                page_cap=per_signal_cap,
            )
            sections.append(text)
            printed.extend(question_id for ids in sources[:kept] for question_id in ids)
    logger.debug("[Insights] find_gaps signal=%s offset=%d", signal, offset)
    footer = (
        "These are heuristic candidates: verify important ones with "
        "read_conversation and present counts as indicative."
    )
    page = ToolPage("\n\n".join(sections) + f"\n\n{footer}", printed)
    return await _release_page(tool.session_id, page)


@mcp.tool(title="List ratings", annotations=_READS, structured_output=False)
async def list_ratings(
    ctx: Context,
    start: str,
    end: str,
    rating: Literal["bad", "good", "all"] = "all",
    comments_only: bool = False,
    offset: int = 0,
    limit: int = 50,
    timezone: str = "UTC",
) -> str:
    """Ratings people gave the target's answers and whole conversations in a
    window, with their comments, newest rating first.

    Use this for "which answers got a bad rating", "what do people complain
    about", "what did people write in their feedback" or "are people happy
    with the answers". For counts alone, the number of lines and the total
    in the header are enough; there is no separate count tool.

    rating picks bad, good or all ratings; comments_only=true keeps only
    ratings that carry a comment. An answer rating belongs to the window of
    its question; a conversation rating (website widget votes land there)
    counts in every window the conversation had a question in, and its line
    shows the conversation's first question. Ratings never say who gave them.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the displayed times. Output is one page;
    when a continuation notice appears, call again with the given offset.
    Cite examples as (session <uuid>).
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    limit = max(1, min(limit, LIST_LIMIT_CEILING))
    value = {"bad": -1, "good": 1, "all": None}[rating]
    filter_note = f"{rating} ratings" + (", with a comment" if comments_only else "")
    async with insight_tool_context(ctx) as tool:
        rows, total, _ = await tool.container.insights_repo().list_ratings(
            tool.scope,
            window,
            source=None,
            value=value,
            has_comment=True if comments_only else None,
            limit=limit,
            after=None,
            offset=offset,
        )
        page = _ratings_text(
            rows,
            total=total,
            offset=offset,
            filter_note=filter_note,
            window=window,
            label=tool.target_label,
            page_cap=default_page_cap(),
        )
    logger.debug(
        "[Insights] list_ratings offset=%d rows=%d total=%d", offset, len(rows), total
    )
    return await _release_page(tool.session_id, page)


@mcp.tool(title="Knowledge use", annotations=_READS, structured_output=False)
async def knowledge_use(
    ctx: Context,
    start: str,
    end: str,
    offset: int = 0,
    timezone: str = "UTC",
) -> str:
    """Which knowledge sources the target's answers cited in a window, and
    which attached sources no answer cited.

    Use this for "which knowledge is used", "is the website/collection used
    at all", "which sources could we remove" or "where do the answers come
    from". For answers that searched the knowledge without a usable hit, use
    find_gaps with signal no_knowledge instead.

    Per collection, website or integration knowledge it counts the answers
    that cited at least one passage from it, injected or fetched through the
    knowledge tool, and its share of the answers that cited anything; a
    group chat's attached sources are its member assistants' together. A
    refreshed document keeps counting; a removed document's citations are
    gone with it, so a source can be undercounted after documents were
    removed. Present the counts as indicative.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the window shown. When a continuation
    notice appears, call again with the given offset.

    It returns counts and source names only, never the text of a question or
    answer, so it adds no source conversations to this analysis.
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    async with insight_tool_context(ctx) as tool:
        citations = await tool.container.insights_repo().knowledge_citations(
            tool.scope, window, source=None
        )
        label = tool.target_label
    logger.debug(
        "[Insights] knowledge_use cited=%d unused=%d",
        len(citations.cited),
        len(citations.unused),
    )
    # Counts and source names only: no text from the conversations.
    return _knowledge_use_text(
        citations,
        offset=offset,
        window=window,
        label=label,
        page_cap=default_page_cap(),
    )


@mcp.tool(title="Tool use", annotations=_READS, structured_output=False)
async def tool_use(
    ctx: Context,
    start: str,
    end: str,
    offset: int = 0,
    timezone: str = "UTC",
) -> str:
    """How often the target's answers called each tool or capability in a
    window, and how often those calls failed or were denied.

    Use this for "which tools are used", "does the web search work", "which
    tool fails" or "do people refuse tool calls". A capability (web search,
    image generation and the like) is one line whichever server backs it;
    other tools are one line per server and tool. A call failed when the
    tool reported an error; it was denied when the person (or the approval
    timeout) did not approve it. Eneo's own knowledge tools are left out
    (use knowledge_use) and so are Skill activations.

    start and end are ISO-8601 datetimes with a UTC offset (end exclusive);
    timezone is the IANA zone for the window shown. When a continuation
    notice appears, call again with the given offset.

    It returns counts and tool names only, never the text of a question or
    answer, so it adds no source conversations to this analysis.
    """
    try:
        window = _parse_window(start, end, timezone)
    except ValueError as exc:
        return str(exc)
    offset = max(0, offset)
    async with insight_tool_context(ctx) as tool:
        rows = await tool.container.insights_repo().tool_use(
            tool.scope, window, source=None
        )
        label = tool.target_label
    logger.debug("[Insights] tool_use tools=%d", len(rows))
    # Counts and tool names only: no text from the conversations.
    return _tool_use_text(
        rows, offset=offset, window=window, label=label, page_cap=default_page_cap()
    )


# --------------------------------------------------------------------------- #
# Ephemeral-server builder
# --------------------------------------------------------------------------- #
async def build_insights_mcp_server(
    *, token: str, tenant_id: UUID, target_label: str
) -> MCPServer:
    """Build the ephemeral MCP server the insights chat attaches to a turn.

    Every tool description is suffixed with the analysed target so the model
    never has to guess whose conversations it is looking at.
    """
    suffix = f"\n\nTarget: {target_label}."
    suffixes = {tool.name: suffix for tool in await mcp.list_tools()}
    return await build_ephemeral_server(
        mcp,
        name=INSIGHTS_SERVER_NAME,
        description=f"Loopback server for analysing conversations with {target_label}.",
        token=token,
        tenant_id=tenant_id,
        tool_description_suffixes=suffixes,
    )
