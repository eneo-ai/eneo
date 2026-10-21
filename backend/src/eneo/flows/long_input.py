"""Flow admission and result projection for the shared digest core from #1091.

The completion-model layer owns segmentation and reduction. Flows only bound
inputs, choose explicit groups, and require complete coverage downstream.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from eneo.completion_models.application.map_reduce import (
    DigestBudgets,
    DigestDeadlineExceeded,
    DigestItem,
    DigestPlan,
    Usage,
    batch_reduce_prompt,
    final_prompt,
    item_reduce_prompt,
    map_prompt,
    plan_segments,
    run_digest,
)

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_SEGMENTS = 120
MAX_CALLS = 256
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class LongInputError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    text: str
    file_id: str | None = None


@dataclass(frozen=True)
class LongPlan:
    sources: tuple[Source, ...]
    plans: tuple[DigestPlan, ...]
    budgets: DigestBudgets
    instruction: str
    summary_instruction: str | None


def prepare_long_input(
    sources: list[Source],
    *,
    mode: str,
    section_tokens: int,
    window: int,
    output_tokens: int,
    tokens: Callable[[str], int],
    prompt: str,
    context: str,
    summary_prompt: str | None,
) -> LongPlan:
    if not sources or len(sources) > 32:
        raise LongInputError("Select between one and 32 non-empty text sources.")
    if sum(len(source.text.encode()) for source in sources) > MAX_SOURCE_BYTES:
        raise LongInputError("Extracted material exceeds the 8 MiB processing limit.")
    for source in sources:
        if not source.text.strip():
            raise LongInputError(
                f"Source '{source.name}' has no extracted text or transcript."
            )
    instruction = prompt + ("\n\nContext:\n" + context if context else "")
    cap = min(2000, output_tokens, window // 4)
    prompts = [
        map_prompt(instruction, 250),
        item_reduce_prompt(instruction, 400),
        batch_reduce_prompt(instruction, 900),
        final_prompt(instruction, 1200) + (summary_prompt or ""),
    ]
    room = window - max(tokens(text) for text in prompts) - cap - 256
    if room < 256 or cap < 128:
        raise LongInputError(
            "The instructions leave too little model context for document processing."
        )
    budgets = DigestBudgets(
        segment_tokens=min(section_tokens, room),
        reduce_input_tokens=room,
        map_max_tokens=min(1200, cap),
        item_max_tokens=min(1500, cap),
        batch_max_tokens=cap,
        final_max_tokens=cap,
    )
    items = [DigestItem(source.key, source.name, source.text) for source in sources]
    whole = plan_segments(items, budgets, tokens)
    if whole.total_segments > MAX_SEGMENTS:
        raise LongInputError(
            f"Material needs more than {MAX_SEGMENTS} segments; use separate runs."
        )
    if mode == "summarize":
        plans = [whole]
    elif mode == "per_source":
        plans = [plan_segments([item], budgets, tokens) for item in items]
    else:
        plans = [
            plan_segments(
                [
                    DigestItem(
                        f"{item.item.key}S{index + 1}",
                        f"{item.item.title} / {index + 1}",
                        text,
                    )
                ],
                budgets,
                tokens,
            )
            for item in whole.items
            for index, text in enumerate(item.segments)
        ]
    return LongPlan(tuple(sources), tuple(plans), budgets, instruction, summary_prompt)


async def process_long_input(
    plan: LongPlan,
    *,
    complete: Callable[[str, str, int, bool], Awaitable[tuple[str, Usage]]],
    tokens: Callable[[str], int],
    should_stop: Callable[[], Awaitable[bool]],
) -> tuple[dict[str, Any], int, int]:
    """One deadline across groups. Never return partial coverage as a success."""
    deadline = time.monotonic() + 300
    calls = size = incoming = outgoing = 0
    answers: list[str] = []
    coverage: list[dict[str, Any]] = []
    # Provider lookup uses the run's session. Nested digest merges must not
    # issue concurrent operations on that session.
    slot = asyncio.Semaphore(1)

    async def call(
        system: str, text: str, max_tokens: int, *, final: bool = False
    ) -> tuple[str, Usage]:
        nonlocal calls, size
        async with slot:
            if await should_stop():
                raise asyncio.CancelledError()
            calls += 1
            if calls > MAX_CALLS or size > MAX_OUTPUT_BYTES:
                raise LongInputError(
                    "Document processing exceeds its call or output limit."
                )
            try:
                async with asyncio.timeout_at(deadline):
                    answer, usage = await complete(system, text, max_tokens, final)
            except TimeoutError as exc:
                raise DigestDeadlineExceeded() from exc
            size += len(answer.encode())
            return answer, usage

    async def final(system: str, text: str, max_tokens: int) -> tuple[str, Usage]:
        if plan.summary_instruction:
            system += "\n\nSynthesis instructions:\n" + plan.summary_instruction
        return await call(system, text, max_tokens, final=True)

    for group in plan.plans:
        result = await run_digest(
            group,
            call,
            instruction=plan.instruction,
            budgets=plan.budgets,
            count=tokens,
            deadline=deadline,
            should_stop=should_stop,
            map_batch=1,
            complete_final=final,
        )
        progress = {key: asdict(value) for key, value in result.item_progress.items()}
        coverage.append(
            {
                "coverage": result.coverage,
                "items": progress,
                "not_relevant": result.not_relevant,
                "reasons": result.reasons,
                "excluded": result.excluded,
                "levels": result.levels,
            }
        )
        if (
            result.coverage != "complete"
            or calls > MAX_CALLS
            or size > MAX_OUTPUT_BYTES
        ):
            raise LongInputError(
                "Document processing was incomplete: "
                + ", ".join(result.reasons or [result.coverage])
            )
        incoming += result.usage.input_tokens
        outgoing += result.usage.output_tokens
        header = (
            f"[{group.items[0].item.key}] {group.items[0].item.title}\n"
            if len(plan.plans) > 1
            else ""
        )
        answers.append(header + result.output)
    return (
        {
            "text": "\n\n".join(answers),
            "value": None,
            "sources": [
                {
                    "source_id": source.key,
                    "file_id": source.file_id,
                    "name": source.name,
                }
                for source in plan.sources
            ],
            "coverage": coverage,
            "processing_calls": calls,
            "words_read": sum(len(source.text.split()) for source in plan.sources),
            "words_answered": sum(len(answer.split()) for answer in answers),
        },
        incoming,
        outgoing,
    )
