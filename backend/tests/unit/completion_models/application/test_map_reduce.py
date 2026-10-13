"""The map-reduce core: segment planning, hierarchical reduce, and the
coverage account that says what the answer leaves out."""

from __future__ import annotations

import asyncio

import pytest

from eneo.completion_models.application.map_reduce import (
    NOT_RELEVANT,
    DigestBudgets,
    DigestDeadlineExceeded,
    DigestItem,
    Usage,
    batch_by_tokens,
    parse_map_output,
    plan_segments,
    run_digest,
)


def _count(text: str) -> int:
    """Whitespace tokens: deterministic and cheap for planning tests."""
    return len(text.split())


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _budgets(**overrides) -> DigestBudgets:
    defaults = dict(segment_tokens=50, reduce_input_tokens=120)
    defaults.update(overrides)
    return DigestBudgets(**defaults)


class _ScriptedModel:
    """A ``complete`` that answers by stage and records every call."""

    def __init__(self, *, fail_on: set[str] | None = None, usage=(10, 5)):
        self.calls: list[tuple[str, str, int]] = []
        self.fail_on = fail_on or set()
        self.usage = Usage(*usage)

    async def __call__(self, system: str, user: str, max_tokens: int):
        self.calls.append((system, user, max_tokens))
        for marker in self.fail_on:
            if marker in user:
                raise RuntimeError(f"failed on {marker}")
        if system.startswith("You take notes"):
            key = user.split("]")[0].strip("[")
            if "irrelevant" in user:
                return f"Date: unknown\n{NOT_RELEVANT}", self.usage
            return f"Date: 2026-01-0{key[-1]}\nnote from {key}", self.usage
        if system.startswith("Merge notes taken from consecutive"):
            key = user.split("]")[0].strip("[")
            return f"Date: 2026-01-01\n[{key}] merged item note", self.usage
        if system.startswith("Merge notes from several"):
            keys = sorted(
                set(part.split("]")[0].strip("[") for part in user.split("[")[1:])
            )
            return "merged " + " ".join(f"[{k}]" for k in keys), self.usage
        if system.startswith("Answer the instruction"):
            return "FINAL: " + user[:40], self.usage
        raise AssertionError(f"unexpected prompt: {system[:40]}")

    def stage_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for system, _, _ in self.calls:
            stage = system.split(" ")[0]
            counts[stage] = counts.get(stage, 0) + 1
        return counts


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
class TestPlanSegments:
    def test_short_items_are_one_segment_and_long_items_many(self):
        items = [
            DigestItem("D1", "Short", _words(10)),
            DigestItem("D2", "Long", _words(230)),
        ]
        plan = plan_segments(items, _budgets(), _count)

        assert len(plan.items[0].segments) == 1
        assert len(plan.items[1].segments) >= 5
        assert plan.total_segments == 1 + len(plan.items[1].segments)
        assert "".join(plan.items[1].segments).count("w229") == 1

    def test_direct_fits_counts_headers_and_every_text(self):
        small = [DigestItem("D1", "A", _words(30)), DigestItem("D2", "B", _words(30))]
        big = [DigestItem("D1", "A", _words(70)), DigestItem("D2", "B", _words(70))]

        assert plan_segments(small, _budgets(), _count).direct_fits is True
        assert plan_segments(big, _budgets(), _count).direct_fits is False

    def test_batch_by_tokens_is_greedy_and_isolates_oversized_texts(self):
        texts = [_words(40), _words(40), _words(60), _words(200), _words(10)]

        batches = batch_by_tokens(texts, _count, 100)

        assert [len(b) for b in batches] == [2, 1, 1, 1]
        assert batches[2] == [_words(200)]


class TestParseMapOutput:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Date: 2026-03-04\nfacts here", ("2026-03-04", "facts here", True)),
            ("Date: unknown\nfacts", (None, "facts", True)),
            ("date: Unknown\nNOT_RELEVANT", (None, "", False)),
            ("NOT_RELEVANT", (None, "", False)),
            ("Date: 2026-03-04\n", ("2026-03-04", "", False)),
            ("facts without a date line", (None, "facts without a date line", True)),
        ],
    )
    def test_date_line_and_sentinel(self, text, expected):
        assert parse_map_output(text) == expected


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
async def test_direct_path_makes_one_final_call_and_covers_everything():
    model = _ScriptedModel()
    items = [DigestItem("D1", "A", _words(20)), DigestItem("D2", "B", _words(20))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.llm_calls == 1
    assert model.stage_counts() == {"Answer": 1}
    assert "[D1] A" in model.calls[0][1] and "[D2] B" in model.calls[0][1]
    assert result.coverage == "complete"
    assert result.usage == Usage(10, 5)
    assert {k: (p.planned, p.processed) for k, p in result.item_progress.items()} == {
        "D1": (1, 1),
        "D2": (1, 1),
    }


async def test_multi_segment_items_get_an_item_reduce_and_short_ones_do_not():
    model = _ScriptedModel()
    items = [
        DigestItem("D1", "Short", _words(20)),
        DigestItem("D2", "Long", _words(150)),
    ]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    counts = model.stage_counts()
    assert counts["You"] == plan.total_segments
    assert counts["Merge"] == 1  # only D2's segment notes are merged
    assert counts["Answer"] == 1
    assert result.coverage == "complete"
    assert result.levels == 0
    assert result.item_progress["D2"].processed == len(plan.items[1].segments)


async def test_hierarchical_reduce_runs_levels_until_one_batch_fits():
    model = _ScriptedModel()
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=30)
    items = [DigestItem(f"D{i}", f"T{i}", _words(40, f"x{i}")) for i in range(1, 7)]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    assert result.levels >= 1
    assert model.stage_counts()["Answer"] == 1
    assert result.coverage == "complete"
    assert result.excluded == []


async def test_non_shrinking_level_compresses_once_then_reports_excluded_keys():
    class _NoShrink(_ScriptedModel):
        async def __call__(self, system, user, max_tokens):
            if system.startswith("Merge notes from several"):
                self.calls.append((system, user, max_tokens))
                # Echo the input back: the level cannot shrink.
                return user, self.usage
            return await super().__call__(system, user, max_tokens)

    model = _NoShrink()
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=8)
    items = [DigestItem(f"D{i}", f"T{i}", _words(20, f"x{i}")) for i in range(1, 4)]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    batch_prompts = [
        s for s, _, _ in model.calls if s.startswith("Merge notes from several")
    ]
    assert any("450 words" in s for s in batch_prompts)  # halved from 900
    assert result.coverage == "partial"
    assert "excluded at reduce" in result.reasons
    assert result.excluded  # the notes outside the first fitting batch
    assert set(result.excluded) <= {"D1", "D2", "D3"}
    assert result.partial_keys == result.excluded


async def test_failed_segment_is_accounted_and_the_run_continues():
    model = _ScriptedModel(fail_on={"[D2] B (segment 2 of"})
    items = [DigestItem("D1", "A", _words(20)), DigestItem("D2", "B", _words(150))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.coverage == "partial"
    assert "failed segments" in result.reasons
    assert result.failed == ["D2 segment 2"]
    assert result.item_progress["D2"].failed == 1
    assert (
        result.item_progress["D2"].processed == result.item_progress["D2"].planned - 1
    )
    assert result.partial_keys == ["D2"]
    assert result.output.startswith("FINAL")


async def test_not_relevant_items_are_covered_but_listed():
    model = _ScriptedModel()
    items = [
        DigestItem("D1", "A", _words(20)),
        DigestItem("D2", "irrelevant memo", _words(60)),
        DigestItem("D3", "C", _words(60)),
    ]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.not_relevant == ["D2"]
    assert result.coverage == "complete"
    assert result.partial_keys == []


async def test_all_items_not_relevant_skips_the_final_call():
    model = _ScriptedModel()
    items = [
        DigestItem("D1", "irrelevant", _words(60)),
        DigestItem("D2", "irrelevant", _words(60)),
    ]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.output == ""
    assert result.not_relevant == ["D1", "D2"]
    assert "Answer" not in model.stage_counts()
    assert result.coverage == "complete"


async def test_map_admission_stops_when_the_reduce_reserve_is_reached():
    clock = {"t": 0.0}
    model = _ScriptedModel()

    async def ticking(system, user, max_tokens):
        clock["t"] += 10.0
        return await model(system, user, max_tokens)

    items = [DigestItem(f"D{i}", f"T{i}", _words(60, f"x{i}")) for i in range(1, 9)]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        ticking,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        deadline=100.0,
        reduce_reserve_seconds=50.0,
        map_batch=1,
        now=lambda: clock["t"],
    )

    processed = sum(p.processed for p in result.item_progress.values())
    assert 0 < processed < plan.total_segments
    assert result.coverage == "partial"
    assert "deadline" in result.reasons
    unfinished = [k for k, p in result.item_progress.items() if p.processed < p.planned]
    assert result.partial_keys == unfinished
    assert result.output  # the reduces still ran on what exists


async def test_deadline_inside_a_call_ends_the_map_as_partial():
    calls = 0

    async def complete(system, user, max_tokens):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise DigestDeadlineExceeded()
        return "Date: unknown\nnote", Usage(1, 1)

    items = [DigestItem(f"D{i}", f"T{i}", _words(60, f"x{i}")) for i in range(1, 6)]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, complete, instruction="sum", budgets=_budgets(), count=_count, map_batch=1
    )

    assert result.coverage == "partial"
    assert "deadline" in result.reasons
    assert result.failed == []  # a deadline is not a provider failure
    assert result.usage == Usage(2, 2)
    assert result.output.startswith("Notes, not merged:")


async def test_deadline_at_the_final_call_hands_back_the_notes():
    model = _ScriptedModel()
    clock = {"t": 0.0}

    async def ticking(system, user, max_tokens):
        text, usage = await model(system, user, max_tokens)
        if system.startswith("Answer"):
            raise DigestDeadlineExceeded()
        return text, usage

    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        ticking,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        now=lambda: clock["t"],
    )

    assert result.coverage == "partial"
    assert result.output.startswith("Notes, not merged:")
    assert "[D1] A" in result.output and "[D2] B" in result.output


async def test_should_stop_returns_cancelled_with_usage_spent():
    model = _ScriptedModel()
    stops = iter([False, False, True])  # run start, batch 1, batch 2

    async def should_stop() -> bool:
        return next(stops, True)

    items = [DigestItem(f"D{i}", f"T{i}", _words(60, f"x{i}")) for i in range(1, 6)]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        model,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        should_stop=should_stop,
        map_batch=2,
    )

    assert result.coverage == "cancelled"
    assert result.llm_calls == 2
    assert result.usage == Usage(20, 10)
    assert result.output == ""


async def test_oversized_item_note_is_split_and_reduced_before_batching():
    class _LongItemNote(_ScriptedModel):
        async def __call__(self, system, user, max_tokens):
            if system.startswith("Merge notes taken from consecutive"):
                self.calls.append((system, user, max_tokens))
                return "Date: unknown\n[D1] " + _words(300, "n"), self.usage
            return await super().__call__(system, user, max_tokens)

    model = _LongItemNote()
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=100)
    items = [
        DigestItem("D1", "Long", _words(150, "a")),
        DigestItem("D2", "B", _words(20, "b")),
    ]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    counts = model.stage_counts()
    assert counts["Merge"] >= 1 + 3  # the item reduce plus one call per piece
    assert result.coverage == "complete"
    assert result.excluded == []


async def test_usage_is_summed_over_every_call():
    model = _ScriptedModel(usage=(7, 3))
    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.llm_calls == len(model.calls)
    assert result.usage == Usage(7 * len(model.calls), 3 * len(model.calls))


async def test_map_batch_bounds_concurrency():
    running = 0
    peak = 0

    async def complete(system, user, max_tokens):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0)
        running -= 1
        return "Date: unknown\nnote [D1]", Usage(1, 1)

    items = [DigestItem(f"D{i}", f"T{i}", _words(60, f"x{i}")) for i in range(1, 10)]
    plan = plan_segments(items, _budgets(), _count)

    await run_digest(
        plan, complete, instruction="sum", budgets=_budgets(), count=_count, map_batch=3
    )

    assert peak <= 3
