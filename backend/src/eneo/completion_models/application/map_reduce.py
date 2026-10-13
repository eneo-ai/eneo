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
notes it had to leave out.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

NOT_RELEVANT = "NOT_RELEVANT"
_DATE_LINE = re.compile(r"^\s*Date:\s*(\S.*?)\s*$", re.IGNORECASE)

Coverage = Literal["complete", "partial", "cancelled"]


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
    map_max_tokens: int = 600
    item_max_tokens: int = 800
    batch_max_tokens: int = 1_500
    final_max_tokens: int = 2_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


CompleteFn = Callable[[str, str, int], Awaitable[tuple[str, Usage]]]
"""``complete(system_prompt, user_input, max_tokens) -> (text, usage)``."""


@dataclass(frozen=True)
class PlannedItem:
    item: DigestItem
    segments: tuple[str, ...]
    tokens: int


@dataclass(frozen=True)
class DigestPlan:
    items: tuple[PlannedItem, ...]
    total_segments: int
    direct_fits: bool


@dataclass
class ItemProgress:
    planned: int
    processed: int = 0
    failed: int = 0


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
    levels: int = 0

    @property
    def partial_keys(self) -> list[str]:
        """Keys whose material is not fully represented in ``output``."""
        keys = [
            key
            for key, progress in self.item_progress.items()
            if progress.processed < progress.planned
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
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=budgets.segment_tokens,
        chunk_overlap=budgets.segment_tokens // 20,
        length_function=count,
    )
    planned: list[PlannedItem] = []
    total_tokens = 0
    for item in items:
        tokens = count(item.text)
        total_tokens += tokens + count(_item_header(item))
        if tokens <= budgets.segment_tokens:
            segments: tuple[str, ...] = (item.text,)
        else:
            segments = tuple(splitter.split_text(item.text)) or (item.text,)
        planned.append(PlannedItem(item=item, segments=segments, tokens=tokens))
    total_segments = sum(len(p.segments) for p in planned)
    return DigestPlan(
        items=tuple(planned),
        total_segments=total_segments,
        direct_fits=total_tokens <= budgets.reduce_input_tokens,
    )


def batch_by_tokens(
    texts: Sequence[str], estimate: Callable[[str], int], budget: int
) -> list[list[str]]:
    """Greedy batching in order; a text over the budget gets its own batch."""
    batches: list[list[str]] = []
    current: list[str] = []
    used = 0
    for text in texts:
        size = estimate(text)
        if current and used + size > budget:
            batches.append(current)
            current, used = [], 0
        current.append(text)
        used += size
    if current:
        batches.append(current)
    return batches


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
        f"{words} words. Do not describe the material or your method; do "
        "not add facts that the material does not contain.\n\n"
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
    ) -> None:
        self.plan = plan
        self.complete = complete
        self.instruction = instruction
        self.budgets = budgets
        self.count = count
        self.deadline = deadline
        self.reduce_reserve = reduce_reserve_seconds
        self.should_stop = should_stop
        self.map_batch = max(1, map_batch)
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

    async def check_stop(self) -> bool:
        if self.cancelled:
            return True
        if self.should_stop is not None and await self.should_stop():
            self.cancelled = True
            self.note_reason("cancelled")
            return True
        return False

    async def call(self, system: str, user: str, max_tokens: int) -> str | None:
        """One model call; ``None`` when it failed or the deadline passed."""
        if self.out_of_time():
            self.deadline_hit = True
            self.note_reason("deadline")
            return None
        try:
            text, usage = await self.complete(system, user, max_tokens)
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
        self.usage = self.usage + usage
        return text

    # -- stages ----------------------------------------------------------- #
    async def direct(self) -> str:
        parts = [f"{_item_header(p.item)}\n\n{p.item.text}" for p in self.plan.items]
        text = await self.call(
            final_prompt(self.instruction, self.budgets.final_words),
            "Documents:\n\n" + "\n\n---\n\n".join(parts),
            self.budgets.final_max_tokens,
        )
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
        position = 0
        while position < len(tasks):
            if await self.check_stop():
                break
            if self.out_of_time(self.reduce_reserve):
                self.deadline_hit = True
                self.note_reason("deadline")
                break
            batch = tasks[position : position + self.map_batch]
            position += len(batch)
            results = await asyncio.gather(
                *(
                    self.call(
                        system,
                        f"{_item_header(p.item)} (segment {index + 1} of "
                        f"{len(p.segments)})\n\n{p.segments[index]}",
                        self.budgets.map_max_tokens,
                    )
                    for p, index in batch
                )
            )
            for (p, index), text in zip(batch, results):
                progress = self.progress[p.item.key]
                if text is None:
                    progress.failed += 1
                    if not self.deadline_hit:
                        self.failed.append(f"{p.item.key} segment {index + 1}")
                    continue
                progress.processed += 1
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

        for start in range(0, len(pending), self.map_batch):
            batch = pending[start : start + self.map_batch]
            if await self.check_stop():
                for p, joined in batch:
                    result.append(self._fallback_note(p, joined))
                continue
            texts = await asyncio.gather(
                *(
                    self.call(
                        system,
                        f"{_item_header(p.item)}\n\n{joined}",
                        self.budgets.item_max_tokens,
                    )
                    for p, joined in batch
                )
            )
            for (p, joined), text in zip(batch, texts):
                if text is None:
                    result.append(self._fallback_note(p, joined))
                else:
                    date, body, _ = parse_map_output(text)
                    result.append(
                        _Note((p.item.key,), _format_note(p.item, date, body))
                    )
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
                return self._first_fitting(notes, batches)
            self.levels += 1
            merged = await self._reduce_level(notes, batches, words)
            if len(merged) < len(notes):
                notes = merged
                continue
            if not compressed_once:
                compressed_once = True
                words = max(100, words // 2)
                continue
            return self._first_fitting(notes, batches)

    async def _reduce_level(
        self, notes: list[_Note], batches: list[list[str]], words: int
    ) -> list[_Note]:
        system = batch_reduce_prompt(self.instruction, words)
        grouped: list[list[_Note]] = []
        cursor = 0
        for batch in batches:
            grouped.append(notes[cursor : cursor + len(batch)])
            cursor += len(batch)
        merged: list[_Note] = []
        for start in range(0, len(grouped), self.map_batch):
            chunk = grouped[start : start + self.map_batch]
            texts = await asyncio.gather(
                *(
                    self.call(
                        system,
                        "\n\n---\n\n".join(n.text for n in group),
                        self.budgets.batch_max_tokens,
                    )
                    for group in chunk
                )
            )
            for group, text in zip(chunk, texts):
                keys = tuple(dict.fromkeys(k for n in group for k in n.keys))
                if text is None:
                    merged.extend(group)
                else:
                    merged.append(_Note(keys, text.strip()))
        return merged

    def _first_fitting(
        self, notes: list[_Note], batches: list[list[str]]
    ) -> list[_Note]:
        kept = len(batches[0])
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
            if self.count(note.text) <= budget:
                out.append(note)
                continue
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=budget, chunk_overlap=0, length_function=self.count
            )
            pieces = splitter.split_text(note.text)
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
        text = await self.call(
            final_prompt(self.instruction, self.budgets.final_words),
            f"Notes:\n\n{material}",
            self.budgets.final_max_tokens,
        )
        if text is not None:
            return text.strip()
        # The deadline or the provider ended the run: hand back the notes
        # themselves rather than nothing, flagged as unmerged.
        self.note_reason("notes not merged")
        return "Notes, not merged:\n\n" + material

    def result(self, output: str) -> DigestResult:
        if self.cancelled:
            coverage: Coverage = "cancelled"
        elif (
            self.deadline_hit
            or self.failed
            or self.excluded
            or any(p.processed < p.planned for p in self.progress.values())
            or "notes not merged" in self.reasons
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
) -> DigestResult:
    """Run the plan to one answer with an explicit coverage account.

    ``deadline`` is a ``now()`` timestamp after which no call starts; map
    admission already stops when less than ``reduce_reserve_seconds`` remain
    so the reduces get their share. ``should_stop`` is awaited before each
    map batch and each reduce level; True ends the run as ``cancelled`` with
    the usage spent so far. ``map_batch`` calls run concurrently; the caller
    bounds the provider side with its own semaphore inside ``complete``.
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
    )
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
    "Usage",
    "batch_by_tokens",
    "batch_reduce_prompt",
    "final_prompt",
    "item_reduce_prompt",
    "map_prompt",
    "parse_map_output",
    "plan_segments",
    "run_digest",
]
