# pyright: basic
"""Glue between the loopback digest tools and the map-reduce core.

Both ``digest_documents`` (knowledge server) and ``digest_files`` (files
server) do the same thing with different inputs: select texts, plan segments
against the completion's effective model, run the core with a bounded,
retried, deadline-aware ``complete``, and format one result that says what
it covers. Everything model- and MCP-shaped lives here so the two tools stay
thin and the core stays pure.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mcp.types import (
    ContentBlock,
    EmbeddedResource,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl

from eneo.ai_models.completion_models.completion_model import Context
from eneo.completion_models.application.map_reduce import (
    DigestBudgets,
    DigestDeadlineExceeded,
    DigestItem,
    DigestPlan,
    DigestResult,
    ProgressFn,
    Stage,
    Usage,
    final_prompt,
    plan_segments,
    run_digest,
)
from eneo.internal_mcp.constants import CITE_KEY_META
from eneo.internal_mcp.foundation import DigestClaims, default_page_cap
from eneo.main.config import get_settings
from eneo.main.exceptions import OpenAIException
from eneo.model_providers.infrastructure.litellm_transport import (
    NON_RETRYABLE_PROVIDER_ERRORS,
)
from eneo.tokens.token_utils import count_tokens

logger = logging.getLogger(__name__)

INSTRUCTION_MAX_CHARS = 2_000
TITLE_MAX_CHARS = 120
STUB_MAX_CHARS = 160
# Share of the proxy's output cap one digest result may fill, header, body and
# citation stubs together, leaving room for the proxy's own framing.
PAYLOAD_SHARE = 0.75
# The body takes the whole page: the header and citation stubs ride outside
# it under the payload cap, and a 50-row chronological list needs the room.
BODY_PAGE_SHARE = 1.0
# Provider reasons worth a retry: the request was fine, the provider was not.
RETRYABLE_REASONS = frozenset({"provider_rate_limited", "provider_unavailable"})
MAX_ATTEMPTS = 3
CALL_TIMEOUT_SECONDS = 90.0
DEADLINE_MARGIN_SECONDS = 15.0
REDUCE_RESERVE_SHARE = 0.3

# All digests in one process share this cap, whatever the per-digest
# concurrency: gunicorn runs several workers, each with its own.
_PROCESS_SLOTS = asyncio.Semaphore(16)

_KEY = re.compile(r"\[(D\d+)\]")


class DigestRefused(Exception):
    """Carries the text a tool returns instead of running."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_instruction(instruction: str) -> str:
    text = instruction.strip()
    if not text:
        raise DigestRefused("Pass an instruction: what to extract or answer.")
    if len(text) > INSTRUCTION_MAX_CHARS:
        raise DigestRefused(
            f"The instruction is {len(text)} characters; keep it under "
            f"{INSTRUCTION_MAX_CHARS}."
        )
    return text


def clip_title(title: str | None, fallback: str = "Untitled") -> str:
    text = (title or "").strip() or fallback
    return text[:TITLE_MAX_CHARS]


# --------------------------------------------------------------------------- #
# Model resolution and budgets
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReaderTarget:
    """The tenant's reader model, taking the segment notes and item merges."""

    model: Any
    adapter: Any
    model_kwargs: dict[str, Any]
    count: Callable[[str], int]
    segment_tokens: int


@dataclass(frozen=True)
class DigestModel:
    model: Any
    adapter: Any
    model_kwargs: dict[str, Any]
    count: Callable[[str], int]
    budgets: DigestBudgets
    body_cap_chars: int
    reader: ReaderTarget | None = None
    # Why the ask path settled on that reader, or on none (``ReaderReason``).
    reader_reason: str | None = None

    @property
    def segment_count(self) -> Callable[[str], int]:
        """The counter of the model that reads the segments."""
        return self.reader.count if self.reader is not None else self.count

    @property
    def models_label(self) -> str:
        if self.reader is None:
            return str(self.model.name)
        return f"{self.model.name} (notes by {self.reader.model.name})"


def body_cap_chars() -> int:
    return int(default_page_cap() * BODY_PAGE_SHARE)


def _lowest_reasoning_effort(model: Any) -> str | None:
    capability = model.get_supported_model_kwargs().reasoning_effort
    if not capability.supported or not capability.options:
        return None
    return capability.options[0]


async def prepare_digest_model(
    tool_ctx: Any, assistant: Any, claims: DigestClaims, *, instruction: str
) -> DigestModel:
    """The effective model, its adapter, kwargs and token budgets.

    The model comes from the token's claim (the ask path minted it after
    governance resolution), falling back to the assistant's own. Reasoning
    effort is the claimed value when a policy enforces it, otherwise the
    cheapest the model supports: notes and merges do not need deep thought.

    A claimed reader model takes the segment notes and per-item merges; the
    segments are then sized to its window while the reduce budgets stay with
    the turn's model, which writes the answer.
    """
    container = tool_ctx.container
    model = None
    if claims.completion_model_id is not None:
        model = await container.completion_model_repo2().one(claims.completion_model_id)
    if model is None:
        model = assistant.completion_model
    if model is None:
        raise DigestRefused("This assistant has no completion model to digest with.")

    supported = model.get_supported_model_kwargs()
    kwargs = assistant.completion_model_kwargs.filter_unsupported(supported)
    model_kwargs = kwargs.model_dump(exclude_none=True)
    model_kwargs.pop("response_format", None)
    if (
        claims.reasoning_enforced
        and claims.reasoning_effort
        and supported.reasoning_effort.accepts(claims.reasoning_effort)
    ):
        model_kwargs["reasoning_effort"] = claims.reasoning_effort
    else:
        lowest = _lowest_reasoning_effort(model)
        if lowest is not None:
            model_kwargs["reasoning_effort"] = lowest
        else:
            model_kwargs.pop("reasoning_effort", None)

    adapter = await container.completion_service().build_adapter(model)
    route = model.get_model_route()

    def count(text: str) -> int:
        return count_tokens(text, route)

    budgets = compute_budgets(
        window=model.max_input_tokens,
        count=count,
        instruction=instruction,
        body_cap=body_cap_chars(),
    )
    reader = await _prepare_reader(container, claims, model, instruction=instruction)
    if reader is not None:
        budgets = replace(budgets, segment_tokens=reader.segment_tokens)
    return DigestModel(
        model=model,
        adapter=adapter,
        model_kwargs=model_kwargs,
        count=count,
        budgets=budgets,
        body_cap_chars=body_cap_chars(),
        reader=reader,
        reader_reason=claims.reader_reason,
    )


def notes_kwargs(model: Any, model_kwargs: dict[str, Any]) -> dict[str, Any]:
    """The kwargs for the notes and merges: the given ones at temperature 0.

    Notes are extraction, not prose, and a digest is many calls: sampling
    noise in every note compounds through the merges into run-to-run
    variance, so the stages before the answer sample as little as the model
    allows. A model that takes no temperature keeps its kwargs as they are.
    """
    kwargs = dict(model_kwargs)
    if model.get_supported_model_kwargs().temperature.accepts(0.0):
        kwargs["temperature"] = 0.0
    return kwargs


async def _prepare_reader(
    container: Any, claims: DigestClaims, turn_model: Any, *, instruction: str
) -> ReaderTarget | None:
    """The claimed reader model, ready to call, or None to stay on one model.

    The ask path judged it against the space and the policy; here it only
    has to exist and hold a segment. It always runs at its lowest reasoning
    effort: notes do not need deep thought, and speed is its whole point.
    """
    if claims.reader_model_id is None or claims.reader_model_id == turn_model.id:
        return None
    model = await container.completion_model_repo2().one_or_none(claims.reader_model_id)
    if model is None:
        logger.warning("[digest] reader model %s not found", claims.reader_model_id)
        return None
    route = model.get_model_route()

    def count(text: str) -> int:
        return count_tokens(text, route)

    try:
        budgets = compute_budgets(
            window=model.max_input_tokens,
            count=count,
            instruction=instruction,
            body_cap=body_cap_chars(),
        )
    except DigestRefused:
        logger.warning("[digest] reader model %s window too small", model.name)
        return None
    model_kwargs = notes_kwargs(model, {})
    lowest = _lowest_reasoning_effort(model)
    if lowest is not None:
        model_kwargs["reasoning_effort"] = lowest
    adapter = await container.completion_service().build_adapter(model)
    return ReaderTarget(
        model=model,
        adapter=adapter,
        model_kwargs=model_kwargs,
        count=count,
        segment_tokens=budgets.segment_tokens,
    )


def compute_budgets(
    *, window: int, count: Callable[[str], int], instruction: str, body_cap: int
) -> DigestBudgets:
    """Token budgets net of prompt overhead and output reserve.

    Refuses when the model's window cannot hold one segment or one reduce
    batch with its prompt and reply.
    """
    # Eight characters a word, spaces and citation keys included, so the
    # answer tends to land under the page; the core re-asks once when over.
    final_words = max(300, body_cap // 8)
    final_max_tokens = body_cap // 3 + 200
    # The longest prompt plus chat framing; the instruction rides in each.
    overhead = count(final_prompt(instruction, final_words)) + 64
    segment_room = window - overhead - DigestBudgets.map_max_tokens
    reduce_room = window - overhead - final_max_tokens
    if segment_room < 1_000 or reduce_room < 4_000:
        raise DigestRefused(
            "The completion model's context window is too small for a digest; "
            "use read_source or read_file on one document at a time."
        )
    segment_tokens = max(1_000, min(segment_room // 4, 12_000))
    reduce_input_tokens = max(4_000, min(reduce_room // 2, 60_000))
    return DigestBudgets(
        segment_tokens=segment_tokens,
        reduce_input_tokens=reduce_input_tokens,
        final_words=final_words,
        final_max_tokens=final_max_tokens,
        final_chars=body_cap,
    )


# --------------------------------------------------------------------------- #
# Planning and refusals
# --------------------------------------------------------------------------- #
# The resolver's reason when the turn's model is itself the flagged reader:
# reading on it is then the cheap option by definition, so no cap applies.
TURN_MODEL_IS_READER = "same_as_turn"

# What to tell the user when no reader took the notes, by the resolver's reason.
_NO_READER_WHY: dict[str, str] = {
    "no_tenant_default": (
        "no reader model is enabled for the organisation; an administrator "
        "can enable one under Models"
    ),
    "none": "this space has no reader model chosen",
    "tenant_default_below_classification": (
        "the organisation's reader model is below this space's security classification"
    ),
    "own_below_classification": (
        "the space's reader model is below its security classification"
    ),
    "policy_disallows": (
        "the personal-assistant policy does not allow the reader model"
    ),
}
_NO_READER_WHY_DEFAULT = "no reader model is available for this turn"


def turn_model_cap(digest_model: DigestModel) -> int | None:
    """The most tokens of material a digest may read on the turn model
    alone, or None when a reader takes the notes.

    The reader is what makes a large digest cheap: without one, every
    segment and merge would run on the turn's own model, which the user may
    have chosen for its quality rather than its price. So without a reader
    the digest reads at most what fits one call of the turn model (the
    direct path, which costs the same as reading the material outright),
    unless the ``digest_turn_model_max_tokens`` setting says otherwise.
    """
    if digest_model.reader is not None:
        return None
    if digest_model.reader_reason == TURN_MODEL_IS_READER:
        return None
    cap = get_settings().digest_turn_model_max_tokens
    return digest_model.budgets.reduce_input_tokens if cap is None else cap


def refuse_over_turn_cap(
    digest_model: DigestModel, *, items: int, tokens: int, narrow_hint: str
) -> None:
    """Refuse ``tokens`` of material on the turn model alone when over the
    cap, saying why no reader is there and what would change that."""
    cap = turn_model_cap(digest_model)
    if cap is None or tokens <= cap:
        return
    why = _NO_READER_WHY.get(digest_model.reader_reason or "", _NO_READER_WHY_DEFAULT)
    if cap == 0:
        raise DigestRefused(
            f"A digest here needs a reader model, and {why}. Open the "
            "documents one at a time instead."
        )
    raise DigestRefused(
        f"Too much text for a digest without a reader model: {items} items "
        f"with about {tokens:,} tokens, the limit on the completion model alone "
        f"is {cap:,} tokens. A reader model would take the notes at lower "
        f"cost, but {why}. {narrow_hint}"
    )


def plan_or_refuse(
    items: Sequence[DigestItem],
    digest_model: DigestModel,
    *,
    narrow_hint: str,
) -> DigestPlan:
    """Plan the segments or refuse with counts and the way to narrow."""
    ceiling = get_settings().digest_max_segments
    plan = plan_segments(items, digest_model.budgets, digest_model.segment_count)
    if plan.total_segments > ceiling:
        largest = sorted(plan.items, key=lambda p: len(p.segments), reverse=True)[:3]
        named = "; ".join(
            f"[{p.item.key}] {p.item.title} ({len(p.segments)} segments)"
            for p in largest
        )
        raise DigestRefused(
            f"Too much text for one digest: {len(items)} items need "
            f"{plan.total_segments} segments, the limit is {ceiling}. Largest: "
            f"{named}. {narrow_hint}"
        )
    refuse_over_turn_cap(
        digest_model,
        items=len(items),
        tokens=plan.total_tokens,
        narrow_hint=narrow_hint,
    )
    return plan


def estimated_segments(total_chars: int, digest_model: DigestModel) -> int:
    """A cheap upper bound before any text is loaded (four chars per token)."""
    return (total_chars // 4) // max(1, digest_model.budgets.segment_tokens) + 1


# --------------------------------------------------------------------------- #
# The provider call: bounded, retried, deadline-aware
# --------------------------------------------------------------------------- #
class Deadline:
    def __init__(self, seconds: float, *, now: Callable[[], float] = time.monotonic):
        self.now = now
        self.at = now() + seconds

    def remaining(self) -> float:
        return self.at - self.now()


async def _acquire(semaphore: asyncio.Semaphore, deadline: Deadline) -> None:
    remaining = deadline.remaining()
    if remaining <= 0:
        raise DigestDeadlineExceeded()
    try:
        async with asyncio.timeout(remaining):
            await semaphore.acquire()
    except TimeoutError:
        raise DigestDeadlineExceeded() from None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, NON_RETRYABLE_PROVIDER_ERRORS):
        return False
    if not isinstance(exc, OpenAIException):
        return False
    details = exc.details or {}
    return details.get("reason") in RETRYABLE_REASONS


class ProviderCalls:
    """``complete`` for the core: one adapter call under both semaphores.

    Every wait (slot, backoff, the call itself) is bounded by the deadline
    so the digest returns before the proxy's tool-call budget on every
    path. Rate limits and provider outages are retried with jittered
    backoff; a hung call past ``CALL_TIMEOUT_SECONDS`` counts as a failed
    call, not a deadline.
    """

    def __init__(
        self,
        digest_model: DigestModel,
        *,
        deadline: Deadline,
        concurrency: int,
        process_slots: asyncio.Semaphore = _PROCESS_SLOTS,
        sleep: Callable[[float], Any] = asyncio.sleep,
        rng: Callable[[float, float], float] = random.uniform,
        target: Any = None,
        slots: asyncio.Semaphore | None = None,
    ) -> None:
        """Calls on ``target`` (adapter and kwargs; the digest model itself
        by default, or its reader target), sharing ``slots`` when given so
        two targets of one digest stay under one concurrency bound."""
        self.digest_model = digest_model
        self.target = target if target is not None else digest_model
        self.deadline = deadline
        self.slots = (
            slots if slots is not None else asyncio.Semaphore(max(1, concurrency))
        )
        self.process_slots = process_slots
        self.sleep = sleep
        self.rng = rng

    async def __call__(
        self, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        await _acquire(self.process_slots, self.deadline)
        try:
            await _acquire(self.slots, self.deadline)
            try:
                return await self._attempts(system, user, max_tokens)
            finally:
                self.slots.release()
        finally:
            self.process_slots.release()

    async def _attempts(
        self, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        context = Context(prompt=system, input=user)
        kwargs = {**self.target.model_kwargs, "max_tokens": max_tokens}
        attempt = 0
        while True:
            attempt += 1
            remaining = self.deadline.remaining()
            if remaining <= 0:
                raise DigestDeadlineExceeded()
            try:
                async with asyncio.timeout(min(CALL_TIMEOUT_SECONDS, remaining)):
                    completion = await self.target.adapter.get_response(context, kwargs)
            except TimeoutError:
                if self.deadline.remaining() <= 0:
                    raise DigestDeadlineExceeded() from None
                raise ProviderCallTimeout() from None
            except Exception as exc:
                if attempt >= MAX_ATTEMPTS or not is_retryable(exc):
                    raise
                backoff = min(self.rng(1.0, min(20.0, 2.0**attempt)), 20.0)
                if backoff >= self.deadline.remaining():
                    raise DigestDeadlineExceeded() from exc
                await self.sleep(backoff)
                continue
            usage = completion.usage
            return (
                completion.text or "",
                Usage(
                    int((usage.prompt_tokens if usage else 0) or 0),
                    int((usage.completion_tokens if usage else 0) or 0),
                    length_stopped=(
                        getattr(completion, "finish_reason", None) == "length"
                    ),
                ),
            )


class ProviderCallTimeout(RuntimeError):
    """A single provider call hung past ``CALL_TIMEOUT_SECONDS``."""


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #
def progress_reporter(ctx: Any) -> ProgressFn:
    """The core's progress hook as MCP progress notifications on ``ctx``.

    Sent only when the client asked (a progress token on the request), so a
    client that does not care costs nothing. The notification is tied to the
    request it reports on (``related_request_id``): the streamable HTTP
    transport routes a notification without that link to the standalone GET
    stream, which a stateless server never has, so ``ctx.report_progress``
    (which omits the link in mcp 1.28) would silently drop every one. A
    failure to send never reaches the digest.
    """

    async def report(done: int, total: int, stage: Stage) -> None:
        if stage == "reading":
            message = f"Read {done} of {total} parts"
        elif stage == "merging":
            message = "Merging the notes"
        else:
            message = "Writing the answer"
        meta = ctx.request_context.meta
        progress_token = meta.progressToken if meta is not None else None
        if progress_token is None:
            return
        await ctx.session.send_progress_notification(
            progress_token=progress_token,
            progress=done,
            total=total,
            message=message,
            related_request_id=ctx.request_id,
        )

    return report


async def run_bounded_digest(
    plan: DigestPlan,
    digest_model: DigestModel,
    *,
    instruction: str,
    should_stop: Callable[[], Any] | None,
    on_progress: ProgressFn | None = None,
) -> tuple[DigestResult, float]:
    """Run the core under the configured deadline; returns (result, seconds)."""
    settings = get_settings()
    total = max(1.0, settings.digest_timeout_seconds - DEADLINE_MARGIN_SECONDS)
    deadline = Deadline(total)
    # The answer is written under the turn's own kwargs; every call before it
    # (notes, item merges, batch merges) runs at temperature 0 on the same
    # model, or on the reader when one was claimed.
    answer_calls = ProviderCalls(
        digest_model, deadline=deadline, concurrency=settings.digest_concurrency
    )
    notes_calls = ProviderCalls(
        digest_model,
        deadline=deadline,
        concurrency=settings.digest_concurrency,
        target=replace(
            digest_model,
            model_kwargs=notes_kwargs(digest_model.model, digest_model.model_kwargs),
        ),
        slots=answer_calls.slots,
    )
    map_calls = None
    if digest_model.reader is not None:
        map_calls = ProviderCalls(
            digest_model,
            deadline=deadline,
            concurrency=settings.digest_concurrency,
            target=digest_model.reader,
            slots=answer_calls.slots,
        )
    started = time.monotonic()
    result = await run_digest(
        plan,
        notes_calls,
        instruction=instruction,
        budgets=digest_model.budgets,
        count=digest_model.count,
        deadline=deadline.at,
        on_progress=on_progress,
        reduce_reserve_seconds=total * REDUCE_RESERVE_SHARE,
        should_stop=should_stop,
        map_batch=settings.digest_concurrency,
        complete_map=map_calls,
        complete_final=answer_calls,
    )
    return result, time.monotonic() - started


def disconnect_check(ctx: Any) -> Callable[[], Any] | None:
    """``should_stop`` bound to the loopback request, when there is one."""
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    if request is None or not hasattr(request, "is_disconnected"):
        return None

    async def should_stop() -> bool:
        return bool(await request.is_disconnected())

    return should_stop


# --------------------------------------------------------------------------- #
# Result formatting
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SetAside:
    """An item not digested, with the way to reach its content instead."""

    title: str
    reason: str


@dataclass(frozen=True)
class CitationStub:
    """One cited item as a citable resource the adapter links to its key."""

    key: str
    uri: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def cited_keys(output: str, keys: Sequence[str]) -> list[str]:
    wanted = set(keys)
    return [k for k in dict.fromkeys(_KEY.findall(output)) if k in wanted]


def coverage_line(result: DigestResult, *, item_word: str) -> str:
    progress = result.item_progress
    planned = sum(p.planned for p in progress.values())
    processed = sum(p.processed for p in progress.values())
    parts = [
        f"{len(progress)} {item_word}",
        f"{planned} segments planned",
        f"{processed} processed",
    ]
    if result.failed:
        parts.append(f"{len(result.failed)} failed")
    if result.not_relevant:
        keys = ", ".join(f"[{k}]" for k in result.not_relevant)
        parts.append(f"{len(result.not_relevant)} with no relevant content ({keys})")
    counts = "; ".join(parts)
    if result.coverage == "complete":
        return f"Coverage: complete. {counts}."
    reasons = ", ".join(result.reasons) or "incomplete"
    partial = ", ".join(f"[{k}]" for k in result.partial_keys)
    tail = f" Not fully covered: {partial}." if partial else ""
    return f"Coverage: {result.coverage} ({reasons}). {counts}.{tail}"


@dataclass(frozen=True)
class Compression:
    """How much text became how many words, read off the items and the result.

    Every stage squeezes into a fixed word cap, so the ratio says how much
    each fact competed for the answer; the merge levels and the largest
    item say where the squeeze was steepest.
    """

    words_read: int
    words_answered: int
    levels: int
    # The item split into the most segments, when any item needed splitting.
    largest_key: str | None
    largest_segments: int

    @property
    def ratio(self) -> int | None:
        if not self.words_answered:
            return None
        return max(1, round(self.words_read / self.words_answered))


def compression_of(items: Sequence[DigestItem], result: DigestResult) -> Compression:
    largest_key: str | None = None
    largest_segments = 0
    for key, progress in result.item_progress.items():
        if progress.planned > largest_segments:
            largest_key, largest_segments = key, progress.planned
    return Compression(
        words_read=sum(len(item.text.split()) for item in items),
        words_answered=len(result.output.split()),
        levels=result.levels,
        largest_key=largest_key if largest_segments > 1 else None,
        largest_segments=largest_segments,
    )


def compression_line(
    items: Sequence[DigestItem], result: DigestResult, *, item_word: str
) -> str:
    c = compression_of(items, result)
    head = f"Compression: {c.words_read:,} words read into {c.words_answered:,}"
    if c.ratio is not None:
        head += f" ({c.ratio:,}:1)"
    parts = [head]
    if c.levels:
        parts.append(f"{c.levels} merge level{'s' if c.levels != 1 else ''}")
    else:
        parts.append("no merges")
    if c.largest_key is not None:
        parts.append(
            f"largest {item_word.rstrip('s')} [{c.largest_key}] "
            f"{c.largest_segments} segments into one note"
        )
    return "; ".join(parts) + "."


def format_digest(
    *,
    heading: str,
    items: Sequence[DigestItem],
    result: DigestResult,
    set_aside: Sequence[SetAside],
    omitted: int,
    stubs: Sequence[CitationStub],
    body_cap: int,
    item_word: str,
) -> list[ContentBlock]:
    """Header, coverage line, body and citation stubs within the payload cap.

    The body is what shrinks when the payload would exceed the cap: the
    header and the stubs are what lets the model route and cite.
    """
    lines = [heading]
    lines.extend(f"[{item.key}] {item.title}" for item in items)
    if set_aside:
        lines.append("Not digested (tables):")
        lines.extend(f"- {entry.title}: {entry.reason}" for entry in set_aside)
    if omitted:
        lines.append(f"Omitted by max_documents: {omitted} {item_word}.")
    lines.append(coverage_line(result, item_word=item_word))
    lines.append(compression_line(items, result, item_word=item_word))
    header = "\n".join(lines)

    stub_chars = sum(len(stub.text) for stub in stubs)
    payload_cap = int(get_settings().mcp_tool_output_max_chars * PAYLOAD_SHARE)
    cap = max(400, min(body_cap, payload_cap - len(header) - stub_chars))
    body = result.output.strip()
    if not body:
        body = (
            "No content relevant to the instruction was found."
            if result.coverage != "cancelled"
            else "Digest cancelled: the conversation ended before it finished."
        )
    if len(body) > cap:
        body = body[:cap].rstrip() + f"\n[Digest body truncated at {cap} characters.]"

    content: list[ContentBlock] = [TextContent(type="text", text=f"{header}\n\n{body}")]
    for stub in stubs:
        content.append(
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=AnyUrl(stub.uri),
                    mimeType="text/plain",
                    text=stub.text[:STUB_MAX_CHARS],
                    _meta={**stub.meta, CITE_KEY_META: stub.key},
                ),
            )
        )
    return content


def digest_meta(
    result: DigestResult, digest_model: DigestModel, items: Sequence[DigestItem] = ()
) -> dict[str, Any]:
    """The call's ``_meta``: the turn model's usage under the GenAI keys (what
    the question row folds), the reader model's under its own."""
    progress = result.item_progress
    compression = compression_of(items, result)
    meta: dict[str, Any] = {
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": digest_model.model.name,
        "gen_ai.usage.input_tokens": result.usage.input_tokens,
        "gen_ai.usage.output_tokens": result.usage.output_tokens,
        "eneo.completion_model_id": str(digest_model.model.id),
        "eneo.llm_calls": result.llm_calls,
        "eneo.items_matched": len(progress),
        "eneo.segments_planned": sum(p.planned for p in progress.values()),
        "eneo.segments_processed": sum(p.processed for p in progress.values()),
        "eneo.levels": result.levels,
        "eneo.words_read": compression.words_read,
        "eneo.words_answered": compression.words_answered,
        "eneo.coverage": result.coverage,
        "eneo.items_partial": result.partial_keys,
    }
    if digest_model.reader_reason is not None:
        meta["eneo.reader_reason"] = digest_model.reader_reason
    if digest_model.reader is not None:
        meta["eneo.reader_model_id"] = str(digest_model.reader.model.id)
        meta["eneo.reader.model"] = digest_model.reader.model.name
        meta["eneo.reader.input_tokens"] = result.map_usage.input_tokens
        meta["eneo.reader.output_tokens"] = result.map_usage.output_tokens
    return meta


def log_digest(
    tag: str,
    *,
    assistant_id: Any,
    scope: str,
    result: DigestResult,
    digest_model: DigestModel,
    seconds: float,
    items: Sequence[DigestItem] = (),
) -> None:
    progress = result.item_progress
    compression = compression_of(items, result)
    logger.info(
        "%s digest assistant=%s scope=%s model=%s items=%d segments=%d/%d "
        "calls=%d levels=%d words=%d/%d coverage=%s tokens_in=%d tokens_out=%d "
        "reader=%s reader_tokens_in=%d reader_tokens_out=%d seconds=%.1f",
        tag,
        assistant_id,
        scope,
        digest_model.model.name,
        len(progress),
        sum(p.processed for p in progress.values()),
        sum(p.planned for p in progress.values()),
        result.llm_calls,
        result.levels,
        compression.words_read,
        compression.words_answered,
        result.coverage,
        result.usage.input_tokens,
        result.usage.output_tokens,
        digest_model.reader.model.name if digest_model.reader else "-",
        result.map_usage.input_tokens,
        result.map_usage.output_tokens,
        seconds,
    )


__all__ = [
    "CITE_KEY_META",
    "INSTRUCTION_MAX_CHARS",
    "CitationStub",
    "Compression",
    "Deadline",
    "DigestModel",
    "ReaderTarget",
    "DigestRefused",
    "ProviderCallTimeout",
    "ProviderCalls",
    "SetAside",
    "body_cap_chars",
    "cited_keys",
    "clip_title",
    "compression_line",
    "compression_of",
    "compute_budgets",
    "coverage_line",
    "digest_meta",
    "disconnect_check",
    "estimated_segments",
    "format_digest",
    "progress_reporter",
    "is_retryable",
    "log_digest",
    "notes_kwargs",
    "plan_or_refuse",
    "prepare_digest_model",
    "run_bounded_digest",
    "validate_instruction",
]
