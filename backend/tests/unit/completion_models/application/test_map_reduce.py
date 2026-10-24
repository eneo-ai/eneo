"""The map-reduce core: segment planning, hierarchical reduce, and the
coverage account that says what the answer leaves out."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Sequence

import pytest

from eneo.completion_models.application.map_reduce import (
    NOT_RELEVANT,
    DigestBudgets,
    DigestDeadlineExceeded,
    DigestItem,
    Usage,
    _split_by_tokens,
    batch_by_tokens,
    fitting_prefix,
    parse_map_output,
    plan_segments,
    run_digest,
)
from eneo.tokens.token_utils import count_tokens


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

    def __init__(
        self,
        *,
        fail_on: set[str] | None = None,
        usage=(10, 5),
        cut_when: Callable[[str, str], bool] | None = None,
        final_replies: list[str] | None = None,
    ):
        self.calls: list[tuple[str, str, int]] = []
        self.fail_on = fail_on or set()
        self.usage = Usage(*usage)
        # Marks a call as stopped at max_tokens, as a provider would report.
        self.cut_when = cut_when or (lambda system, user: False)
        # Scripted answers for the final calls, in order; the default after.
        self.final_replies = list(final_replies or [])

    async def __call__(self, system: str, user: str, max_tokens: int):
        text, usage = await self._reply(system, user, max_tokens)
        if self.cut_when(system, user):
            usage = Usage(usage.input_tokens, usage.output_tokens, length_stopped=True)
        return text, usage

    async def _reply(self, system: str, user: str, max_tokens: int):
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
            if self.final_replies:
                return self.final_replies.pop(0), self.usage
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

    def test_batch_by_tokens_keeps_order_and_isolates_oversized_texts(self):
        texts = [_words(40), _words(40), _words(60), _words(200), _words(10)]

        batches = batch_by_tokens(texts, _count, 100)

        assert [len(b) for b in batches] == [2, 1, 1, 1]
        assert batches[2] == [_words(200)]

    def test_batch_by_tokens_sizes_batches_evenly_not_greedily(self):
        # Greedy filling would give nine and one; the merge of nine notes
        # would then carry nearly all the compression.
        texts = [_words(10)] * 9 + [_words(55)]

        batches = batch_by_tokens(texts, _count, 100)

        assert [len(b) for b in batches] == [7, 3]
        assert [sum(_count(t) for t in b) for b in batches] == [70, 75]

    def test_fitting_prefix_counts_leading_texts_within_budget(self):
        texts = [_words(40), _words(40), _words(40)]

        assert fitting_prefix(texts, _count, 100) == 2
        assert fitting_prefix(texts, _count, 1000) == 3
        assert fitting_prefix(texts, _count, 10) == 1  # never nothing


def _chars(text: str) -> int:
    """A token per three characters: works on text with no whitespace."""
    return -(-len(text) // 3)


def _assert_tiles(text: str, segments: Sequence[str]) -> None:
    """The segments run through ``text`` in order with no gap but whitespace."""
    covered = 0
    previous = -1
    for segment in segments:
        start = text.find(segment, previous + 1)
        assert start != -1
        assert text[covered:start].strip() == ""
        covered = max(covered, start + len(segment))
        previous = start
    assert text[covered:].strip() == ""


_TEXTS = {
    "newline-free": (_words(600), _count),
    "paragraphs": ("\n\n".join(_words(37, f"p{j}_") for j in range(20)), _count),
    "no-whitespace": ("".join(str(i) for i in range(1_000)), _chars),
    "swedish and cjk": (" ".join(f"ärende{i}å會議記錄ö" for i in range(400)), _count),
    "cjk unspaced": ("".join(chr(0x4E00 + i) for i in range(1_000)), _chars),
}


class TestSegmentSplitting:
    @pytest.mark.parametrize("name", _TEXTS)
    def test_every_segment_fits_and_the_segments_tile_the_text(self, name):
        text, count = _TEXTS[name]
        plan = plan_segments([DigestItem("D1", "T", text)], _budgets(), count)

        segments = plan.items[0].segments
        assert len(segments) > 1
        assert all(count(s) <= 50 for s in segments)
        _assert_tiles(text, segments)

    def test_overlap_repeats_words_but_never_the_last_one(self):
        text = _words(600)
        segments = plan_segments([DigestItem("D1", "T", text)], _budgets(), _count)
        joined = " ".join(segments.items[0].segments).split()

        assert set(joined) == set(text.split())
        assert joined.count("w599") == 1

    def test_the_same_text_splits_the_same_way(self):
        items = [DigestItem("D1", "T", _TEXTS["paragraphs"][0])]

        assert plan_segments(items, _budgets(), _count) == plan_segments(
            items, _budgets(), _count
        )

    @pytest.mark.parametrize("count", [lambda text: 1, len])
    def test_splitting_ends_whatever_the_counter_says(self, count):
        text = _words(500)

        segments = _split_by_tokens(text, count(text), 50, 2, count)

        assert segments
        _assert_tiles(text, segments)
        assert all(count(s) <= 50 for s in segments) or count(text) == 1

    def test_a_long_text_is_measured_a_few_times_per_segment(self):
        calls = 0

        def counting(text: str) -> int:
            nonlocal calls
            calls += 1
            return _count(text)

        items = [DigestItem("D1", "T", _words(20_000))]
        plan = plan_segments(items, _budgets(segment_tokens=1_000), counting)

        # The text and its header once each, then at most three per segment.
        assert plan.total_segments >= 20
        assert calls <= 2 + 3 * plan.total_segments

    @pytest.mark.parametrize(
        ("seed", "words", "limit"), [(120, (25, 80), 50), (51, (600, 1200), 1024)]
    )
    @pytest.mark.parametrize("lead", [" ", ""])
    def test_a_real_tokenizer_counts_the_segment_it_returns(
        self, seed, words, limit, lead
    ):
        # " council" is one o200k token and "council" three, so a piece that
        # fits with its leading space can overflow once the space is stripped.
        def count(text: str) -> int:
            return count_tokens(text, "gpt-4o")

        rng = random.Random(seed)
        vocabulary = (
            "the understanding meeting council municipality sammanträde"
            " beslut protokoll Sundsvall budget, a. of"
        ).split()
        text = lead + " ".join(
            rng.choice(vocabulary) for _ in range(rng.randint(*words))
        )
        plan = plan_segments(
            [DigestItem("D1", "T", text)],
            _budgets(segment_tokens=limit, reduce_input_tokens=10 * limit),
            count,
        )

        segments = plan.items[0].segments
        assert len(segments) > 1
        assert [count(s) for s in segments if count(s) > limit] == []
        _assert_tiles(text, segments)


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
    stops = iter([False, False, False, True])  # run start, then one per map call

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


async def test_an_oversized_note_is_cut_into_fitting_pieces_without_overlap():
    class _LongItemNote(_ScriptedModel):
        async def __call__(self, system, user, max_tokens):
            if system.startswith("Merge notes taken from consecutive"):
                self.calls.append((system, user, max_tokens))
                return "Date: unknown\n[D1] " + _words(300, "n"), self.usage
            return await super().__call__(system, user, max_tokens)

    model = _LongItemNote()
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=100)
    plan = plan_segments([DigestItem("D1", "Long", _words(150, "a"))], budgets, _count)

    await run_digest(plan, model, instruction="sum", budgets=budgets, count=_count)

    pieces = [u for s, u, _ in model.calls if s.startswith("Merge notes from several")]
    assert len(pieces) >= 4
    assert all(_count(piece) <= 100 for piece in pieces)
    words = " ".join(pieces).split()
    assert all(words.count(f"n{i}") == 1 for i in range(300))


async def test_usage_is_summed_over_every_call():
    model = _ScriptedModel(usage=(7, 3))
    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.llm_calls == len(model.calls)
    assert result.usage == Usage(7 * len(model.calls), 3 * len(model.calls))


async def test_a_map_model_takes_notes_and_item_merges_with_its_own_usage():
    turn, utility = _ScriptedModel(usage=(10, 5)), _ScriptedModel(usage=(3, 1))
    items = [DigestItem(f"D{i}", f"T{i}", _words(120, f"x{i}")) for i in range(1, 6)]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        turn,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        complete_map=utility,
    )

    assert utility.calls and turn.calls
    assert all(
        system.startswith(("You take notes", "Merge notes taken from consecutive"))
        for system, _, _ in utility.calls
    )
    assert all(
        system.startswith(("Merge notes from several", "Answer the instruction"))
        for system, _, _ in turn.calls
    )
    assert result.coverage == "complete"
    assert result.llm_calls == len(turn.calls) + len(utility.calls)
    assert result.map_usage == Usage(3 * len(utility.calls), len(utility.calls))
    assert result.usage == Usage(10 * len(turn.calls), 5 * len(turn.calls))

    single = await run_digest(
        plan, _ScriptedModel(), instruction="sum", budgets=_budgets(), count=_count
    )
    assert single.map_usage == Usage()


async def test_a_final_model_writes_the_answer_and_the_notes_model_the_rest():
    notes, final = _ScriptedModel(usage=(3, 1)), _ScriptedModel(usage=(10, 5))
    items = [DigestItem(f"D{i}", f"T{i}", _words(120, f"x{i}")) for i in range(1, 6)]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        notes,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        complete_final=final,
    )

    assert [system[:22] for system, _, _ in final.calls] == ["Answer the instruction"]
    assert notes.calls and not any(
        system.startswith("Answer the instruction") for system, _, _ in notes.calls
    )
    assert result.coverage == "complete"
    # Both functions are the turn model's: one usage account, no map share.
    assert result.usage == Usage(10 + 3 * len(notes.calls), 5 + len(notes.calls))
    assert result.map_usage == Usage()

    direct_plan = plan_segments([DigestItem("D1", "T1", "short")], _budgets(), _count)
    notes, final = _ScriptedModel(), _ScriptedModel()
    await run_digest(
        direct_plan,
        notes,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        complete_final=final,
    )
    assert (len(notes.calls), len(final.calls)) == (0, 1)


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


# --------------------------------------------------------------------------- #
# Calls the provider stopped at max_tokens
# --------------------------------------------------------------------------- #
def _merge_keys(user: str) -> int:
    return len(set(part.split("]")[0] for part in user.split("[")[1:]))


async def test_cut_batch_merge_is_redone_on_halves_and_nothing_is_lost():
    # Four notes in one merge come back cut; pairs merge whole.
    model = _ScriptedModel(
        cut_when=lambda system, user: (
            system.startswith("Merge notes from several") and _merge_keys(user) > 2
        )
    )
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=40)
    items = [DigestItem(f"D{i}", f"T{i}", _words(20, f"x{i}")) for i in range(1, 9)]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    merges = [u for s, u, _ in model.calls if s.startswith("Merge notes from several")]
    assert any(_merge_keys(u) > 2 for u in merges)  # the cut merges happened
    assert all(_merge_keys(u) <= 2 for u in merges if _merge_keys(u) != 4)
    final_input = next(u for s, u, _ in model.calls if s.startswith("Answer"))
    assert all(f"[D{i}]" in final_input for i in range(1, 9))
    assert result.coverage == "complete"
    assert result.excluded == []


async def test_single_note_merge_that_is_cut_is_kept_and_reported():
    model = _ScriptedModel(
        cut_when=lambda system, user: system.startswith("Merge notes from several")
    )
    budgets = _budgets(segment_tokens=50, reduce_input_tokens=8)
    items = [DigestItem(f"D{i}", f"T{i}", _words(20, f"x{i}")) for i in range(1, 4)]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    assert result.coverage == "partial"
    assert "merge cut short" in result.reasons


async def test_cut_segment_notes_mark_the_item_partial_but_are_kept():
    model = _ScriptedModel(
        cut_when=lambda system, user: (
            system.startswith("You take notes") and user.startswith("[D2]")
        )
    )
    # Three one-segment items, over the direct path's budget, so each gets
    # one map call and its note reaches the final call unmerged.
    items = [DigestItem(f"D{i}", f"T{i}", _words(45, f"x{i}")) for i in range(1, 4)]
    plan = plan_segments(items, _budgets(), _count)
    assert not plan.direct_fits

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert result.coverage == "partial"
    assert "notes cut short" in result.reasons
    assert result.partial_keys == ["D2"]
    assert result.item_progress["D2"].cut == 1
    final_input = next(u for s, u, _ in model.calls if s.startswith("Answer"))
    assert "note from D2" in final_input  # what came back is still used


async def test_answer_over_the_page_is_asked_again_tighter():
    long, short = "x " * 60, "fits"
    model = _ScriptedModel(final_replies=[long, short])
    budgets = _budgets(final_chars=40)
    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    finals = [(s, m) for s, _, m in model.calls if s.startswith("Answer")]
    assert len(finals) == 2
    first_words = int(finals[0][0].split("at most ")[1].split(" words")[0])
    second_words = int(finals[1][0].split("at most ")[1].split(" words")[0])
    assert second_words < first_words
    assert result.output == short
    assert result.coverage == "complete"


async def test_answer_cut_by_the_provider_is_asked_again_tighter():
    seen = {"finals": 0}

    def first_final_only(system: str, user: str) -> bool:
        if not system.startswith("Answer"):
            return False
        seen["finals"] += 1
        return seen["finals"] == 1

    model = _ScriptedModel(cut_when=first_final_only)
    items = [DigestItem("D1", "A", _words(20))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=_budgets(), count=_count
    )

    assert model.stage_counts()["Answer"] == 2
    assert result.coverage == "complete"
    assert "answer cut short" not in result.reasons


async def test_answer_still_over_the_page_is_cut_at_a_line_and_reported():
    long = "\n".join(f"line {i} of the answer" for i in range(10))
    model = _ScriptedModel(final_replies=[long, long])
    budgets = _budgets(final_chars=80)
    items = [DigestItem("D1", "A", _words(20))]
    plan = plan_segments(items, budgets, _count)

    result = await run_digest(
        plan, model, instruction="sum", budgets=budgets, count=_count
    )

    assert result.coverage == "partial"
    assert "answer cut short" in result.reasons
    assert len(result.output) <= 80
    assert result.output.endswith("[Answer cut short.]")
    body = result.output.removesuffix("\n[Answer cut short.]")
    assert body.splitlines()[-1].startswith("line ")  # cut at a line, not mid-word
    assert body.splitlines()[-1].endswith("of the answer")


async def test_progress_reports_each_segment_then_the_merges_and_the_answer():
    model = _ScriptedModel()
    reports: list[tuple[int, int, str]] = []

    async def on_progress(done: int, total: int, stage: str) -> None:
        reports.append((done, total, stage))

    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        model,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        on_progress=on_progress,
    )

    total = plan.total_segments
    reading = [r for r in reports if r[2] == "reading"]
    assert [r[0] for r in reading] == list(range(1, total + 1))
    assert all(r[1] == total for r in reading)
    assert reports[-2:] == [(total, total, "merging"), (total, total, "answering")]
    assert result.coverage == "complete"


async def test_a_failing_progress_hook_never_ends_the_run():
    model = _ScriptedModel()

    async def on_progress(done: int, total: int, stage: str) -> None:
        raise RuntimeError("listener gone")

    items = [DigestItem("D1", "A", _words(60)), DigestItem("D2", "B", _words(60))]
    plan = plan_segments(items, _budgets(), _count)

    result = await run_digest(
        plan,
        model,
        instruction="sum",
        budgets=_budgets(),
        count=_count,
        on_progress=on_progress,
    )

    assert result.coverage == "complete"
