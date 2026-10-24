"""Bounded map-reduce over a set of texts with one injected completion call.

The digest tools (``digest_documents`` on the knowledge server and
``digest_files`` on the files server) share this core. It knows nothing
about models, databases or MCP: the caller plans the work from texts it has
already loaded, injects ``complete`` (one model call returning text and
usage) and gets back an answer plus an honest account of what the answer
covers.

Unit of work is a *segment*: a slice of one item's text that fits one map
call. A short item is one segment; a long report is many, and its segment
notes are merged into one item note before the cross-item reduce. When
every text fits one reduce call, the direct path answers in a single call.

Coverage is explicit. ``complete`` means every planned segment was processed
and every item note reached the final reduce; anything less is ``partial``
with the reason and the keys of the items concerned, so the caller can show
exactly what the answer leaves out. Nothing is dropped silently: a reduce
level that cannot shrink its input compresses once more, then reports the
notes it had to leave out; a call the provider stopped at ``max_tokens`` is
retried on halves (merges) or re-asked tighter (the answer), and what is
still cut is reported as such.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Literal, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _Skipped:
    """A map segment never sent: the run was cancelled or out of time."""


_SKIPPED = _Skipped()

NOT_RELEVANT = "NOT_RELEVANT"
_DATE_LINE = re.compile(r"^\s*Date:\s*(\S.*?)\s*$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s")
# Where a segment may end, best first; a hard cut when none is near the end.
_SEPARATORS = ("\n\n", "\n", " ")

Coverage = Literal["complete", "partial", "cancelled"]
# Reasons that on their own make the answer less than the material.
_PARTIAL_REASONS = frozenset(
    {"notes not merged", "answer cut short", "notes cut short", "merge cut short"}
)


class DigestDeadlineExceeded(Exception):
    """Raised by ``complete`` when the digest's deadline passed mid-call."""


@dataclass(frozen=True)
class DigestItem:
    """One text to digest, addressed by a short key the output cites."""

    key: str
    title: str
    text: str


@dataclass(frozen=True)
class DigestBudgets:
    """Token budgets net of prompt overhead and output reserve.

    ``segment_tokens`` is the most text one map call gets;
    ``reduce_input_tokens`` the most note text one reduce call gets. The
    word caps bound each stage's output; the caller turns them into
    ``max_tokens`` through ``complete``'s third argument.
    """

    segment_tokens: int
    reduce_input_tokens: int
    map_words: int = 250
    item_words: int = 400
    batch_words: int = 900
    final_words: int = 1_200
    # Output caps leave room above the word caps: a word of Swedish or German
    # costs closer to two tokens than one, and a cut call loses its tail.
    map_max_tokens: int = 1_200
    item_max_tokens: int = 1_500
    batch_max_tokens: int = 2_200
    final_max_tokens: int = 2_000
    # The most characters the answer may take, when the caller shows it on a
    # page of known size; the final call is re-asked tighter once when over.
    final_chars: int | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # True when the provider stopped at ``max_tokens``: the text is cut short.
    length_stopped: bool = False

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.length_stopped or other.length_stopped,
        )


CompleteFn = Callable[[str, str, int], Awaitable[tuple[str, Usage]]]
"""``complete(system_prompt, user_input, max_tokens) -> (text, usage)``."""

Stage = Literal["reading", "merging", "answering"]
ProgressFn = Callable[[int, int, Stage], Awaitable[None]]
"""``on_progress(segments_done, segments_planned, stage)``: called as each
segment's notes come back, then once when the merges start and once when the
answer is written. Errors it raises are logged, never fatal."""


@dataclass(frozen=True)
class PlannedItem:
    item: DigestItem
    segments: tuple[str, ...]
    tokens: int


@dataclass(frozen=True)
class DigestPlan:
    items: tuple[PlannedItem, ...]
    total_segments: int
    # Every item's text and header as the model that reads them counts it.
    total_tokens: int
    direct_fits: bool


@dataclass
class ItemProgress:
    planned: int
    processed: int = 0
    failed: int = 0
    # Segments whose notes the provider cut at ``max_tokens``.
    cut: int = 0


@dataclass
class DigestResult:
    output: str
    coverage: Coverage
    item_progress: dict[str, ItemProgress]
    failed: list[str] = field(default_factory=list[str])
    excluded: list[str] = field(default_factory=list[str])
    not_relevant: list[str] = field(default_factory=list[str])
    reasons: list[str] = field(default_factory=list[str])
    llm_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    # Spent on the map model when one was given; zero otherwise.
    map_usage: Usage = field(default_factory=Usage)
    levels: int = 0

    @property
    def partial_keys(self) -> list[str]:
        """Keys whose material is not fully represented in ``output``."""
        keys = [
            key
            for key, progress in self.item_progress.items()
            if progress.processed < progress.planned or progress.cut
        ]
        keys.extend(key for key in self.excluded if key not in keys)
        return keys


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def plan_segments(
    items: Sequence[DigestItem],
    budgets: DigestBudgets,
    count: Callable[[str], int],
) -> DigestPlan:
    """Split every item into segments of at most ``segment_tokens``.

    ``count`` is the caller's token counter for the model that will run the
    calls, so the plan and the provider agree on size. ``direct_fits`` is
    True when all texts together fit one reduce call; the caller then
    answers in a single call instead of mapping.
    """
    planned: list[PlannedItem] = []
    total_tokens = 0
    for item in items:
        tokens = count(item.text)
        total_tokens += tokens + count(_item_header(item))
        if tokens <= budgets.segment_tokens:
            segments: tuple[str, ...] = (item.text,)
        else:
            segments = tuple(
                _split_by_tokens(
                    item.text,
                    tokens,
                    budgets.segment_tokens,
                    budgets.segment_tokens // 20,
                    count,
                )
            ) or (item.text,)
        planned.append(PlannedItem(item=item, segments=segments, tokens=tokens))
    total_segments = sum(len(p.segments) for p in planned)
    return DigestPlan(
        items=tuple(planned),
        total_segments=total_segments,
        total_tokens=total_tokens,
        direct_fits=total_tokens <= budgets.reduce_input_tokens,
    )


def batch_by_tokens(
    texts: Sequence[str], estimate: Callable[[str], int], budget: int
) -> list[list[str]]:
    """Batches in order, as few as the budget allows and evenly sized.

    Greedy filling leaves the last batch with the scraps: one merge squeezes
    forty notes into its word cap while another gets three. Even batches
    spread the compression. A text over the budget gets its own batch.
    """
    sizes = [estimate(text) for text in texts]
    total = sum(sizes)
    target = total / max(1, math.ceil(total / budget)) if budget > 0 else 0
    batches: list[list[str]] = []
    current: list[str] = []
    used = 0
    for text, size in zip(texts, sizes):
        if current and (used + size > budget or used + size / 2 > target):
            batches.append(current)
            current, used = [], 0
        current.append(text)
        used += size
    if current:
        batches.append(current)
    return batches


def fitting_prefix(
    texts: Sequence[str], estimate: Callable[[str], int], budget: int
) -> int:
    """How many leading texts fit one call; at least one."""
    used = 0
    for index, text in enumerate(texts):
        used += estimate(text)
        if used > budget:
            return max(1, index)
    return len(texts)


def parse_map_output(text: str) -> tuple[str | None, str, bool]:
    """``(date, body, relevant)`` from a map call's output.

    The date is whatever follows a leading ``Date:`` line, ``None`` when
    missing or ``unknown``. ``relevant`` is False for the NOT_RELEVANT
    sentinel (alone or as the only content after the date line).
    """
    lines = text.strip().splitlines()
    date: str | None = None
    if lines:
        match = _DATE_LINE.match(lines[0])
        if match:
            value = match.group(1)
            date = None if value.casefold() == "unknown" else value
            lines = lines[1:]
    body = "\n".join(lines).strip()
    if not body or body.strip("`* ").upper() == NOT_RELEVANT:
        return date, "", False
    return date, body, True


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def _item_header(item: DigestItem) -> str:
    return f"[{item.key}] {item.title}"


def map_prompt(instruction: str, words: int) -> str:
    return (
        "You take notes from one segment of a document; the notes are merged "
        "later with notes from other segments and documents to answer the "
        "instruction below. Output rules:\n"
        "1. First line: 'Date: YYYY-MM-DD' when the segment states the "
        "document's own date (meeting date, issue date), otherwise 'Date: "
        "unknown'.\n"
        f"2. Then at most {words} words of notes relevant to the instruction: "
        "concrete names, figures, decisions, dates, and exact wording where "
        "the wording matters. Nothing else, no commentary.\n"
        f"3. If nothing in the segment is relevant, output exactly {NOT_RELEVANT} "
        "after the date line.\n"
        "Write the notes in the language of the instruction.\n\n"
        f"Instruction: {instruction}"
    )


def item_reduce_prompt(instruction: str, words: int) -> str:
    return (
        "Merge notes taken from consecutive segments of one document into one "
        f"note of at most {words} words. First line: 'Date: ...' (the "
        "document's date from the notes, or 'Date: unknown'). Then the "
        "document's key in square brackets followed by the merged facts, "
        "without repetition, keeping concrete names, figures and decisions. "
        "Write in the language of the instruction.\n\n"
        f"Instruction the notes serve: {instruction}"
    )


def batch_reduce_prompt(instruction: str, words: int) -> str:
    return (
        "Merge notes from several documents into one note of at most "
        f"{words} words that keeps every fact useful for the instruction. "
        "Every statement keeps the key(s) in square brackets of the "
        "document(s) that support it, exactly as given (for example [D3]). "
        "Keep the dates with their facts. Drop repetition, never drop a "
        "document's key. Write in the language of the instruction.\n\n"
        f"Instruction the notes serve: {instruction}"
    )


def final_prompt(instruction: str, words: int) -> str:
    return (
        "Answer the instruction using only the material provided. After each "
        "statement, cite the supporting document with its key in square "
        "brackets exactly as given (for example [D3]); never invent or "
        "renumber keys. When the material carries dates, order the answer "
        "chronologically. Write in the language of the instruction, at most "
        f"{words} words. Be compact: no preamble or closing remarks, and one "
        "line per listed item. Do not describe the material or your method; "
        "do not add facts that the material does not contain.\n\n"
        f"Instruction: {instruction}"
    )


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
@dataclass
class _Note:
    keys: tuple[str, ...]
    text: str


class _Run:
    """Mutable state of one ``run_digest`` call."""

    def __init__(
        self,
        plan: DigestPlan,
        complete: CompleteFn,
        *,
        instruction: str,
        budgets: DigestBudgets,
        count: Callable[[str], int],
        deadline: float | None,
        reduce_reserve_seconds: float,
        should_stop: Callable[[], Awaitable[bool]] | None,
        map_batch: int,
        now: Callable[[], float],
        complete_map: CompleteFn | None,
        on_progress: ProgressFn | None = None,
        complete_final: CompleteFn | None = None,
    ) -> None:
        self.plan = plan
        self.complete = complete
        self.complete_map = complete_map
        self.complete_final = complete_final
        self.on_progress = on_progress
        self.segments_done = 0
        self.instruction = instruction
        self.budgets = budgets
        self.count = count
        self.deadline = deadline
        self.reduce_reserve = reduce_reserve_seconds
        self.should_stop = should_stop
        self.map_batch = max(1, map_batch)
        self.window = asyncio.Semaphore(self.map_batch)
        self.now = now
        self.progress = {
            p.item.key: ItemProgress(planned=len(p.segments)) for p in plan.items
        }
        self.failed: list[str] = []
        self.call_errors: list[str] = []
        self.excluded: list[str] = []
        self.not_relevant: list[str] = []
        self.reasons: list[str] = []
        self.llm_calls = 0
        self.usage = Usage()
        self.map_usage = Usage()
        self.levels = 0
        self.cancelled = False
        self.deadline_hit = False

    # -- helpers ---------------------------------------------------------- #
    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        return self.deadline - self.now()

    def out_of_time(self, reserve: float = 0.0) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= reserve

    def note_reason(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)

    async def report(self, stage: Stage) -> None:
        if self.on_progress is None:
            return
        try:
            await self.on_progress(self.segments_done, self.plan.total_segments, stage)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - progress must never end the run
            logger.debug("[digest] progress report failed: %s", type(exc).__name__)

    async def _windowed(self, jobs: Sequence[Callable[[], Awaitable[T]]]) -> list[T]:
        """Run ``jobs`` with at most ``map_batch`` in flight, results in order.

        A sliding window: each job starts as a slot frees, so one slow call
        delays only itself and not a whole round.
        """

        async def run(job: Callable[[], Awaitable[T]]) -> T:
            async with self.window:
                return await job()

        return list(await asyncio.gather(*(run(job) for job in jobs)))

    async def check_stop(self) -> bool:
        if self.cancelled:
            return True
        if self.should_stop is not None and await self.should_stop():
            self.cancelled = True
            self.note_reason("cancelled")
            return True
        return False

    async def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        stage: Literal["map", "reduce", "final"] = "reduce",
    ) -> str | None:
        """One model call's text; ``None`` when it failed or time ran out."""
        reply = await self.call_full(system, user, max_tokens, stage=stage)
        return None if reply is None else reply[0]

    async def call_full(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        stage: Literal["map", "reduce", "final"] = "reduce",
    ) -> tuple[str, bool] | None:
        """One model call: ``(text, cut)``, ``cut`` True when the provider
        stopped at ``max_tokens``; ``None`` when it failed or the deadline
        passed.

        A ``map`` stage call (segment notes, per-item merges) goes to the map
        model when one was given; its usage is kept apart so the caller can
        account for two models. A ``final`` stage call (the answer) goes to
        the final function when one was given; it shares the turn model's
        usage with the merges.
        """
        on_map_model = stage == "map" and self.complete_map is not None
        if on_map_model:
            complete = self.complete_map
        elif stage == "final" and self.complete_final is not None:
            complete = self.complete_final
        else:
            complete = self.complete
        assert complete is not None
        if self.out_of_time():
            self.deadline_hit = True
            self.note_reason("deadline")
            return None
        try:
            text, usage = await complete(system, user, max_tokens)
        except DigestDeadlineExceeded:
            self.deadline_hit = True
            self.note_reason("deadline")
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one failed call must not end the run
            logger.warning("[digest] model call failed: %s", type(exc).__name__)
            self.llm_calls += 1
            self.call_errors.append(type(exc).__name__)
            return None
        self.llm_calls += 1
        if on_map_model:
            self.map_usage = self.map_usage + usage
        else:
            self.usage = self.usage + usage
        return text, usage.length_stopped

    # -- stages ----------------------------------------------------------- #
    async def direct(self) -> str:
        parts = [f"{_item_header(p.item)}\n\n{p.item.text}" for p in self.plan.items]
        text = await self.answer("Documents:\n\n" + "\n\n---\n\n".join(parts))
        if text is None:
            for progress in self.progress.values():
                progress.processed = 0
            return ""
        for progress in self.progress.values():
            progress.processed = progress.planned
        return text

    async def map_segments(self) -> dict[str, list[tuple[str | None, str]]]:
        """Segment notes per item key, in segment order."""
        tasks: list[tuple[PlannedItem, int]] = [
            (p, index) for p in self.plan.items for index in range(len(p.segments))
        ]
        notes: dict[str, list[tuple[str | None, str]]] = {
            p.item.key: [] for p in self.plan.items
        }
        system = map_prompt(self.instruction, self.budgets.map_words)

        async def one(p: PlannedItem, index: int) -> tuple[str, bool] | None | _Skipped:
            # Checked as a slot frees, so a cancel or the reduce reserve stops
            # admission within one call rather than one round.
            if await self.check_stop():
                return _SKIPPED
            if self.out_of_time(self.reduce_reserve):
                self.deadline_hit = True
                self.note_reason("deadline")
                return _SKIPPED
            reply = await self.call_full(
                system,
                f"{_item_header(p.item)} (segment {index + 1} of "
                f"{len(p.segments)})\n\n{p.segments[index]}",
                self.budgets.map_max_tokens,
                stage="map",
            )
            self.segments_done += 1
            await self.report("reading")
            return reply

        results = await self._windowed([partial(one, p, index) for p, index in tasks])
        for (p, index), reply in zip(tasks, results):
            if isinstance(reply, _Skipped):
                continue
            progress = self.progress[p.item.key]
            if reply is None:
                progress.failed += 1
                if not self.deadline_hit:
                    self.failed.append(f"{p.item.key} segment {index + 1}")
                continue
            text, cut = reply
            progress.processed += 1
            if cut:
                # The notes stop mid-way: what is there is kept, and the item
                # is reported as partly covered.
                progress.cut += 1
                self.note_reason("notes cut short")
            date, body, relevant = parse_map_output(text)
            if relevant:
                notes[p.item.key].append((date, body))
        if self.failed:
            self.note_reason("failed segments")
        return notes

    async def item_notes(
        self, segment_notes: dict[str, list[tuple[str | None, str]]]
    ) -> list[_Note]:
        """One note per item; multi-segment items are merged by a model call."""
        result: list[_Note] = []
        system = item_reduce_prompt(self.instruction, self.budgets.item_words)
        pending: list[tuple[PlannedItem, str]] = []
        for p in self.plan.items:
            key = p.item.key
            parts = segment_notes.get(key, [])
            if not parts:
                if self.progress[key].processed == self.progress[key].planned:
                    self.not_relevant.append(key)
                continue
            if len(parts) == 1:
                date, body = parts[0]
                result.append(_Note((key,), _format_note(p.item, date, body)))
                continue
            joined = "\n\n".join(
                f"Segment notes {i + 1}:\nDate: {date or 'unknown'}\n{body}"
                for i, (date, body) in enumerate(parts)
            )
            pending.append((p, joined))

        async def merge(p: PlannedItem, joined: str) -> str | None:
            if await self.check_stop():
                return None
            return await self.call(
                system,
                f"{_item_header(p.item)}\n\n{joined}",
                self.budgets.item_max_tokens,
                stage="map",
            )

        texts = await self._windowed(
            [partial(merge, p, joined) for p, joined in pending]
        )
        for (p, joined), text in zip(pending, texts):
            if text is None:
                result.append(self._fallback_note(p, joined))
            else:
                date, body, _ = parse_map_output(text)
                result.append(_Note((p.item.key,), _format_note(p.item, date, body)))

        return result

    def _fallback_note(self, p: PlannedItem, joined: str) -> _Note:
        """Unmerged segment notes, cut to the reduce budget when needed."""
        text = f"{_item_header(p.item)}\n{joined}"
        if self.count(text) > self.budgets.reduce_input_tokens:
            text = _truncate_to_tokens(
                text, self.budgets.reduce_input_tokens, self.count
            )
            self.excluded.append(p.item.key)
            self.note_reason("excluded at reduce")
        return _Note((p.item.key,), text)

    async def reduce(self, notes: list[_Note]) -> list[_Note]:
        """Hierarchical reduce until one batch fits the final call."""
        await self.report("merging")
        notes = await self._split_oversized(notes)
        words = self.budgets.batch_words
        compressed_once = False
        while True:
            batches = batch_by_tokens(
                [n.text for n in notes],
                self.count,
                self.budgets.reduce_input_tokens,
            )
            if len(batches) <= 1:
                return notes
            if await self.check_stop() or self.out_of_time():
                if self.out_of_time():
                    self.deadline_hit = True
                    self.note_reason("deadline")
                return self._first_fitting(notes)
            self.levels += 1
            merged = await self._reduce_level(notes, batches, words)
            if len(merged) < len(notes):
                notes = merged
                continue
            if not compressed_once:
                compressed_once = True
                words = max(100, words // 2)
                continue
            return self._first_fitting(notes)

    async def _reduce_level(
        self, notes: list[_Note], batches: list[list[str]], words: int
    ) -> list[_Note]:
        system = batch_reduce_prompt(self.instruction, words)
        grouped: list[list[_Note]] = []
        cursor = 0
        for batch in batches:
            grouped.append(notes[cursor : cursor + len(batch)])
            cursor += len(batch)
        results = await self._windowed(
            [partial(self._merge_group, system, group) for group in grouped]
        )
        return [note for group in results for note in group]

    async def _merge_group(self, system: str, group: list[_Note]) -> list[_Note]:
        """One note merging ``group``, or ``group`` as it was when the call
        failed.

        A merge the provider stopped at ``max_tokens`` has lost its tail, so
        the halves are merged apart instead; a single note that still gets
        cut is kept unmerged and reported.
        """
        reply = await self.call_full(
            system,
            "\n\n---\n\n".join(n.text for n in group),
            self.budgets.batch_max_tokens,
        )
        if reply is None:
            return list(group)
        text, cut = reply
        if cut and len(group) > 1:
            half = len(group) // 2
            left, right = await asyncio.gather(
                self._merge_group(system, group[:half]),
                self._merge_group(system, group[half:]),
            )
            return [*left, *right]
        if cut:
            self.note_reason("merge cut short")
            return list(group)
        keys = tuple(dict.fromkeys(k for n in group for k in n.keys))
        return [_Note(keys, text.strip())]

    def _first_fitting(self, notes: list[_Note]) -> list[_Note]:
        """The leading notes one final call can take; the rest are excluded."""
        kept = fitting_prefix(
            [n.text for n in notes], self.count, self.budgets.reduce_input_tokens
        )
        for note in notes[kept:]:
            for key in note.keys:
                if key not in self.excluded:
                    self.excluded.append(key)
        self.note_reason("excluded at reduce")
        return notes[:kept]

    async def _split_oversized(self, notes: list[_Note]) -> list[_Note]:
        """Reduce a note larger than one reduce call in halves first."""
        budget = self.budgets.reduce_input_tokens
        out: list[_Note] = []
        system = batch_reduce_prompt(self.instruction, self.budgets.batch_words)
        for note in notes:
            tokens = self.count(note.text)
            if tokens <= budget:
                out.append(note)
                continue
            pieces = _split_by_tokens(note.text, tokens, budget, 0, self.count)
            texts = await asyncio.gather(
                *(
                    self.call(system, piece, self.budgets.batch_max_tokens)
                    for piece in pieces
                )
            )
            merged = "\n".join(t.strip() for t in texts if t)
            if not merged:
                merged = _truncate_to_tokens(note.text, budget, self.count)
                self.excluded.extend(k for k in note.keys if k not in self.excluded)
                self.note_reason("excluded at reduce")
            out.append(_Note(note.keys, merged))
        return out

    async def final(self, notes: list[_Note]) -> str:
        material = "\n\n---\n\n".join(n.text for n in notes)
        await self.report("answering")
        text = await self.answer(f"Notes:\n\n{material}")
        if text is not None:
            return text
        # The deadline or the provider ended the run: hand back the notes
        # themselves rather than nothing, flagged as unmerged.
        self.note_reason("notes not merged")
        return "Notes, not merged:\n\n" + material

    async def answer(self, material: str) -> str | None:
        """The final call over ``material``, fitted to the page.

        An answer the provider cut at ``max_tokens``, or one longer than
        ``final_chars``, is asked for once more with a tighter word cap. What
        is still over is cut at a line and reported, so the caller's page
        never silently drops the end of a chronological list.
        """
        words = self.budgets.final_words
        reply = await self.call_full(
            final_prompt(self.instruction, words),
            material,
            self.budgets.final_max_tokens,
            stage="final",
        )
        if reply is None:
            return None
        text, cut = reply[0].strip(), reply[1]
        if cut or self._over_page(text):
            words = self._tighter_words(words, text, cut)
            retry = await self.call_full(
                final_prompt(self.instruction, words),
                material,
                self.budgets.final_max_tokens,
                stage="final",
            )
            if retry is not None:
                text, cut = retry[0].strip(), retry[1]
        if cut or self._over_page(text):
            self.note_reason("answer cut short")
            text = self._cut_to_page(text)
        return text

    def _over_page(self, text: str) -> bool:
        cap = self.budgets.final_chars
        return cap is not None and len(text) > cap

    def _tighter_words(self, words: int, text: str, cut: bool) -> int:
        cap = self.budgets.final_chars
        if cap is not None and len(text) > cap:
            # Scale by the overshoot, with a margin for the model's own slack.
            return max(100, int(words * cap / len(text) * 0.85))
        return max(100, words * 2 // 3)

    def _cut_to_page(self, text: str) -> str:
        cap = self.budgets.final_chars
        if cap is None or len(text) <= cap:
            return text
        marker = "\n[Answer cut short.]"
        room = max(0, cap - len(marker))
        head = text[:room]
        line_end = head.rfind("\n")
        if line_end > room // 2:
            head = head[:line_end]
        return head.rstrip() + marker

    def result(self, output: str) -> DigestResult:
        if self.cancelled:
            coverage: Coverage = "cancelled"
        elif (
            self.deadline_hit
            or self.failed
            or self.excluded
            or any(p.processed < p.planned or p.cut for p in self.progress.values())
            or any(reason in self.reasons for reason in _PARTIAL_REASONS)
        ):
            coverage = "partial"
        else:
            coverage = "complete"
        return DigestResult(
            output=output,
            coverage=coverage,
            item_progress=self.progress,
            failed=self.failed,
            excluded=self.excluded,
            not_relevant=self.not_relevant,
            reasons=self.reasons,
            llm_calls=self.llm_calls,
            usage=self.usage,
            map_usage=self.map_usage,
            levels=self.levels,
        )


async def run_digest(
    plan: DigestPlan,
    complete: CompleteFn,
    *,
    instruction: str,
    budgets: DigestBudgets,
    count: Callable[[str], int],
    deadline: float | None = None,
    reduce_reserve_seconds: float = 0.0,
    should_stop: Callable[[], Awaitable[bool]] | None = None,
    map_batch: int = 4,
    now: Callable[[], float] = time.monotonic,
    complete_map: CompleteFn | None = None,
    on_progress: ProgressFn | None = None,
    complete_final: CompleteFn | None = None,
) -> DigestResult:
    """Run the plan to one answer with an explicit coverage account.

    ``complete_map``, when given, takes the segment notes and the per-item
    merges (a fast reader model); ``complete`` keeps the batch merges and
    the final answer. ``complete_final``, when given, writes the answer
    instead (the same model under other settings, say), and ``complete``
    keeps the merges. Usage is accounted per function in the result: the
    map function's apart, the other two together as the turn model's.

    ``deadline`` is a ``now()`` timestamp after which no call starts; map
    admission already stops when less than ``reduce_reserve_seconds`` remain
    so the reduces get their share. ``should_stop`` is awaited before each
    map call and each reduce level; True ends the run as ``cancelled`` with
    the usage spent so far. At most ``map_batch`` calls are in flight; the
    caller bounds the provider side with its own semaphore inside ``complete``.

    ``on_progress`` hears how far the reading has come (segments done of
    planned) and when the merges and the answer start, so a caller can relay
    progress to whoever is waiting.

    A cancellation from outside (the request's task torn down) is logged with
    the work done so far before it propagates, since no result reaches the
    caller then.
    """
    run = _Run(
        plan,
        complete,
        instruction=instruction,
        budgets=budgets,
        count=count,
        deadline=deadline,
        reduce_reserve_seconds=reduce_reserve_seconds,
        should_stop=should_stop,
        map_batch=map_batch,
        now=now,
        complete_map=complete_map,
        on_progress=on_progress,
        complete_final=complete_final,
    )
    try:
        return await _stages(run, plan)
    except asyncio.CancelledError:
        progress = run.progress.values()
        logger.info(
            "[digest] cancelled from outside: calls=%d segments=%d/%d "
            "tokens_in=%d tokens_out=%d map_tokens_in=%d map_tokens_out=%d",
            run.llm_calls,
            sum(p.processed for p in progress),
            sum(p.planned for p in progress),
            run.usage.input_tokens,
            run.usage.output_tokens,
            run.map_usage.input_tokens,
            run.map_usage.output_tokens,
        )
        raise


async def _stages(run: _Run, plan: DigestPlan) -> DigestResult:
    if not plan.items:
        return run.result("")
    if await run.check_stop():
        return run.result("")
    if plan.direct_fits:
        return run.result(await run.direct())

    segment_notes = await run.map_segments()
    if run.cancelled:
        return run.result("")
    notes = await run.item_notes(segment_notes)
    if not notes:
        return run.result("")
    notes = await run.reduce(notes)
    if run.cancelled:
        return run.result("")
    return run.result(await run.final(notes))


def _format_note(item: DigestItem, date: str | None, body: str) -> str:
    return f"{_item_header(item)}\nDate: {date or 'unknown'}\n{body}"


def _split_by_tokens(
    text: str, total: int, limit: int, overlap: int, count: Callable[[str], int]
) -> list[str]:
    """``text`` in stripped pieces of at most ``limit`` tokens, in order.

    ``total`` is the caller's count of the whole text. Its characters per
    token size each window, which ends at the best separator in its last
    fifth; one count checks the stripped piece, the text returned, because
    stripping can change how the rest tokenizes, and a piece over ``limit``
    shrinks by the overshoot until it fits or is one character. Each piece
    re-measures the density, so a few counts per piece replace one per
    separator, and the next piece starts ``overlap`` tokens back, at a word
    start.
    """
    size = len(text)
    chars_per_token = size / max(total, 1)
    pieces: list[str] = []
    start = 0
    while start < size:
        end = min(size, start + max(1, int(limit * chars_per_token * 0.97)))
        while True:
            if end < size:
                floor = start + (end - start) * 4 // 5
                for separator in _SEPARATORS:
                    cut = text.rfind(separator, floor, end)
                    if cut > start:
                        end = cut + len(separator)
                        break
            piece = text[start:end].strip()
            used = count(piece)
            if used <= limit or end - start <= 1:
                break
            end = start + max(1, int((end - start) * limit / used * 0.97))
        if piece:
            pieces.append(piece)
        if end >= size:
            break
        chars_per_token = (end - start) / max(used, 1)
        back = end - int(overlap * chars_per_token)
        if start < back and (space := _WHITESPACE.search(text, back, end)):
            back = space.end()
        start = back if start < back < end else end
    return pieces


def _truncate_to_tokens(text: str, budget: int, count: Callable[[str], int]) -> str:
    if count(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if count(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low]


__all__ = [
    "NOT_RELEVANT",
    "CompleteFn",
    "Coverage",
    "DigestBudgets",
    "DigestDeadlineExceeded",
    "DigestItem",
    "DigestPlan",
    "DigestResult",
    "ItemProgress",
    "PlannedItem",
    "ProgressFn",
    "Stage",
    "Usage",
    "batch_by_tokens",
    "batch_reduce_prompt",
    "final_prompt",
    "fitting_prefix",
    "item_reduce_prompt",
    "map_prompt",
    "parse_map_output",
    "plan_segments",
    "run_digest",
]
