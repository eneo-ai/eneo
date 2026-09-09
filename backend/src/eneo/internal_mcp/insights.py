# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server exposing insights analysis tools.

The tools read the conversations users had with one target assistant or
group chat, for an operator analysing how it is used. The bearer token's
``insight_target_type`` / ``insight_target_id`` claims fix the target; every
call re-checks the operator's insight access for it. See
:mod:`eneo.internal_mcp.foundation` for the hosting and authentication model
shared by all internal servers.

All time arguments are ISO-8601 with a UTC offset plus an IANA ``timezone``
that fixes calendar boundaries and displayed times, so "yesterday" means the
operator's yesterday. Every tool self-caps its output with
:func:`default_page_cap` and continues via ``offset``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import Context, FastMCP

from eneo.analysis.insight_scope import InsightScope, InsightTargetKind, InsightWindow
from eneo.analysis.insights_repo import (
    Granularity,
    QuestionRow,
    TopQuestionRow,
    UsageSummary,
)
from eneo.internal_mcp.constants import INSIGHTS_SERVER_NAME
from eneo.internal_mcp.foundation import (
    bearer_from_ctx,
    bootstrap_tool_container,
    build_ephemeral_server,
    default_page_cap,
    fit_lines,
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
# Question text shown per line; long messages are cut so one page still
# lists many questions. read_conversation (phase 2) shows full text.
QUESTION_PREVIEW_CHARS = 300

mcp = FastMCP(
    name="Eneo Insights",
    stateless_http=True,
    instructions=(
        "Analysis tools over the conversations users had with one Eneo "
        "assistant or group chat. Scope is fixed by the access token; tools "
        "take no target id. Always call a tool before answering, page through "
        "truncated output before summarising, and cite conversations by "
        "session id."
    ),
)


class InsightToolContext(NamedTuple):
    """User-bound DI container + identity + scope for one insights tool call."""

    container: Any
    user: Any
    scope: InsightScope
    target_label: str


def insight_target_from_token(token: str) -> tuple[InsightTargetKind, UUID]:
    """The analysed target this token was minted for."""
    claims = verified_claims(token)
    kind = claims.get("insight_target_type")
    raw = claims.get("insight_target_id")
    if kind not in ("assistant", "group_chat") or not raw:
        raise ValueError("Access token is not scoped to an insights target.")
    return kind, UUID(str(raw))


def target_label(kind: InsightTargetKind, name: str) -> str:
    noun = "assistant" if kind == "assistant" else "group chat"
    return f"{noun} '{name}'"


@asynccontextmanager
async def insight_tool_context(ctx: Context):
    """Bootstrap a user-bound container and verify insight access.

    Access is re-checked on every call (``AnalysisService.assert_insight_access``)
    so a token minted before insights were disabled for the target, or before
    the operator lost access, stops working immediately.
    """
    token = bearer_from_ctx(ctx)
    kind, target_id = insight_target_from_token(token)
    async with bootstrap_tool_container(token) as (container, user):
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
        )


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
            f"{summary.api_key_conversations})"
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
) -> str:
    if total == 0:
        return f"No questions for {label} in {_format_window(window)}."
    if not rows:
        return f"Offset {offset} is past the end ({total} questions)."
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
    return f"{header}\n{body}"


def _top_questions_text(
    rows: list[TopQuestionRow],
    *,
    total: int,
    include_followups: bool,
    window: InsightWindow,
    label: str,
    page_cap: int,
) -> str:
    if total == 0 or not rows:
        return f"No questions for {label} in {_format_window(window)}."
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
    return f"{header}\n" + "\n".join(kept) + f"\n\n{footer}"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool(title="Usage summary")
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
    distinct users exclude API-key traffic, which is counted separately.
    Periods with no activity are omitted from the breakdown.
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
    return _usage_summary_text(summary, window, granularity, label)


@mcp.tool(title="List questions")
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
        label = tool.target_label
    logger.debug(
        "[Insights] list_questions target=%s window=%s offset=%d rows=%d total=%d",
        label,
        _format_window(window),
        offset,
        len(rows),
        total,
    )
    return _list_questions_text(
        rows,
        total=total,
        offset=offset,
        include_followups=include_followups,
        window=window,
        label=label,
        page_cap=default_page_cap(),
    )


@mcp.tool(title="Top questions")
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
        label = tool.target_label
    logger.debug(
        "[Insights] top_questions target=%s window=%s n=%d groups=%d total=%d",
        label,
        _format_window(window),
        n,
        len(rows),
        total,
    )
    return _top_questions_text(
        rows,
        total=total,
        include_followups=include_followups,
        window=window,
        label=label,
        page_cap=default_page_cap(),
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
