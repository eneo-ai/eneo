import asyncio

import pytest

from eneo.completion_models.application.map_reduce import Usage
from eneo.flows.long_input import (
    LongInputError,
    Source,
    prepare_long_input,
    process_long_input,
)


def prepare(sources, mode="summarize", section_tokens=256):
    return prepare_long_input(
        sources,
        mode=mode,
        section_tokens=section_tokens,
        window=8000,
        output_tokens=2000,
        tokens=len,
        prompt="Extract facts",
        context="",
        summary_prompt="Synthesize facts" if mode == "summarize" else None,
    )


async def keep_running():
    return False


def test_shared_planner_includes_every_source_and_the_tail():
    text = "\n".join(f"Rad {i} med åäö och 🙂." for i in range(100)) + " LAST_SENTINEL"
    plan = prepare([Source("D1", "Report", text)])
    segments = plan.plans[0].items[0].segments
    assert len(segments) > 1
    assert "LAST_SENTINEL" in segments[-1]
    assert all(len(segment) <= 256 for segment in segments)


def test_limits_fail_instead_of_dropping_material():
    with pytest.raises(LongInputError, match="120"):
        prepare([Source("D1", "Large", "x" * 100000)])
    with pytest.raises(LongInputError, match="no extracted"):
        prepare([Source("D1", "Scan", " ")])


async def test_per_source_preserves_source_links_order_and_usage():
    plan = prepare(
        [
            Source("D1", "First", "one", "file-a"),
            Source("D2", "Second", "two", "file-b"),
        ],
        mode="per_source",
    )
    calls = []

    async def complete(prompt, text, max_tokens, final):
        calls.append((prompt, text, max_tokens, final))
        return "answer", Usage(10, 5)

    output, incoming, outgoing = await process_long_input(
        plan, complete=complete, tokens=len, should_stop=keep_running
    )
    assert incoming == 20 and outgoing == 10
    assert [source["file_id"] for source in output["sources"]] == ["file-a", "file-b"]
    assert "[D1]" in output["text"] and "[D2]" in output["text"]
    assert all(result["coverage"] == "complete" for result in output["coverage"])


async def test_partial_provider_results_never_become_successful_step_output():
    plan = prepare([Source("D1", "Report", "one")])

    async def complete(prompt, text, max_tokens, final):
        raise RuntimeError("provider unavailable")

    with pytest.raises(LongInputError, match="incomplete"):
        await process_long_input(
            plan, complete=complete, tokens=len, should_stop=keep_running
        )


async def test_cancelled_processing_starts_no_provider_calls():
    plan = prepare([Source("D1", "Report", "one")])
    calls = []

    async def complete(*args):
        calls.append(args)
        return "", Usage()

    async def stop():
        return True

    with pytest.raises((LongInputError, asyncio.CancelledError)):
        await process_long_input(plan, complete=complete, tokens=len, should_stop=stop)
    assert calls == []
