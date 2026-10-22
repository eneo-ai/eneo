from __future__ import annotations

from dataclasses import replace

import pytest

from eneo.completion_models.application.map_reduce import (
    DigestItem,
    DigestResult,
    ItemProgress,
    Usage,
    map_prompt,
    plan_segments,
    run_digest,
)
from eneo.flows.domain.long_material import (
    CALL_CEILING_REASON,
    DEFAULT_INSTRUCTION,
    NOTHING_RELEVANT,
    REMAINDER_TITLE,
    STAGE_DEFAULTS,
    TOKEN_CEILING_REASON,
    WHOLE_INPUT_TITLE,
    DigestCallLimits,
    DigestCallRecord,
    LongMaterialConfig,
    SourceCandidate,
    admit_digest,
    build_coverage,
    cited_sources,
    describe_left_out,
    digest_budgets,
    digest_instruction,
    digest_time_limits,
    final_call,
    final_question,
    is_map_call,
    long_material_config,
    map_call_target,
    minimum_digest_calls,
    minimum_digest_input_tokens,
    partial_coverage_error,
    partial_coverage_outcome,
    partition_digest_sources,
    reduce_call,
    without_direct_path,
)
from eneo.flows.domain.provider_call import DigestCallInput
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException


def words(text: str) -> int:
    return len(text.split())


def candidate(title: str, text: str) -> SourceCandidate:
    return SourceCandidate(title=title, text=text, reference={"kind": "test"})


# --------------------------------------------------------------------------- #
# Setting
# --------------------------------------------------------------------------- #
def test_the_setting_is_read_from_input_config_and_absent_means_off():
    assert long_material_config(None) is None
    assert long_material_config({"text_processing": {"mode": "summarize"}}) is None
    assert long_material_config({"long_material": {"mode": "digest"}}) == (
        LongMaterialConfig.model_validate({"mode": "digest"})
    )


def test_an_unknown_mode_or_field_is_refused():
    with pytest.raises(ValueError):
        long_material_config({"long_material": {"mode": "truncate"}})
    with pytest.raises(ValueError):
        long_material_config({"long_material": {"mode": "digest", "reader": "x"}})


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def test_sources_split_the_input_at_its_candidates_and_concatenate_to_it():
    question = (
        "Källa 1\nFilnamn: a.pdf\n\nAlpha text.\n\n"
        "Källa 2\nFilnamn: b.pdf\n\nBeta text.\n\nAnswer briefly."
    )
    sources = partition_digest_sources(
        question,
        [candidate("b.pdf", "Beta text."), candidate("a.pdf", "Alpha text.")],
    )

    assert [source.title for source in sources] == ["a.pdf", "b.pdf", REMAINDER_TITLE]
    assert "".join(source.text for source in sources) == question
    assert sources[0].start_char == 0
    assert sources[1].start_char == sources[0].end_char
    assert sources[0].text.startswith("Källa 1")
    assert [source.key for source in sources] == ["S1", "S2", "S3"]


def test_trailing_blank_text_stays_with_the_last_source():
    question = "Header\n\nOnly text.\n\n"
    sources = partition_digest_sources(question, [candidate("doc", "Only text.")])

    assert len(sources) == 1
    assert sources[0].text == question


def test_a_candidate_not_found_verbatim_makes_the_whole_input_one_source():
    question = "Rewritten by a template: ALPHA."
    sources = partition_digest_sources(question, [candidate("a", "Alpha.")])

    assert [(source.title, source.text) for source in sources] == [
        (WHOLE_INPUT_TITLE, question)
    ]
    assert sources[0].reference["kind"] == "step_input"


def test_brackets_in_titles_cannot_pass_for_source_keys():
    sources = partition_digest_sources(
        "x [S9] y", [candidate("Report [S9]\n draft", "x [S9] y")]
    )

    assert sources[0].title == "Report (S9) draft"


# --------------------------------------------------------------------------- #
# Instruction and the final call's input
# --------------------------------------------------------------------------- #
def test_the_notes_follow_the_step_instructions_without_its_output_format():
    rules = ("Return ONLY valid JSON.", "Schema: {...}")
    prompt = "Summarise the decisions.\n\nReturn ONLY valid JSON.\nSchema: {...}"

    assert digest_instruction(prompt, rules) == "Summarise the decisions."
    assert digest_instruction("\n".join(rules), rules) == DEFAULT_INSTRUCTION
    assert digest_instruction("Plain prompt.", ()) == "Plain prompt."


def test_the_final_input_lists_the_sources_before_the_notes():
    sources = partition_digest_sources(
        "A text. B text.", [candidate("a", "A text."), candidate("b", "B text.")]
    )

    question = final_question(sources=sources, notes="Notes:\n\n[S1] fact")

    assert "[S1] a\n[S2] b" in question
    assert question.endswith("Notes:\n\n[S1] fact")
    assert final_question(sources=sources, notes="  ") == NOTHING_RELEVANT


# --------------------------------------------------------------------------- #
# Budgets and admission
# --------------------------------------------------------------------------- #
def test_budgets_take_a_quarter_of_the_map_room_and_the_tighter_merge_room():
    budgets = digest_budgets(map_room=4_000, reduce_room=6_000, final_room=3_000)

    assert budgets is not None
    assert budgets.segment_tokens == 1_000
    assert budgets.reduce_input_tokens == 2_700
    assert budgets.map_words == STAGE_DEFAULTS.map_words


def test_a_model_too_small_for_a_useful_segment_or_merge_has_no_budgets():
    assert digest_budgets(map_room=150, reduce_room=6_000, final_room=6_000) is None
    assert digest_budgets(map_room=4_000, reduce_room=6_000, final_room=300) is None


def test_the_plan_always_reads_in_segments_and_counts_its_least_calls():
    items = [
        DigestItem(key="S1", title="long", text=" ".join(["w"] * 2_500)),
        DigestItem(key="S2", title="short", text="a few words"),
    ]
    budgets = digest_budgets(map_room=4_000, reduce_room=60_000, final_room=60_000)
    assert budgets is not None
    plan = plan_segments(items, budgets, words)
    assert plan.direct_fits

    closed = without_direct_path(plan)

    assert not closed.direct_fits
    segments = closed.total_segments
    assert segments == len(closed.items[0].segments) + 1 > 3
    # A note per segment, one merge for the long source, the final call.
    assert minimum_digest_calls(closed, fallback_call_possible=False) == segments + 2
    assert minimum_digest_calls(closed, fallback_call_possible=True) == segments + 3
    assert minimum_digest_input_tokens(closed, map_overhead_tokens=10) == (
        closed.total_tokens + 10 * segments
    )


def test_admission_follows_the_organization_mapped_execution_policy():
    admit_digest(
        step_order=2,
        needed_calls=5,
        needed_input_tokens=900,
        call_ceiling=5,
        token_ceiling=900,
    )
    with pytest.raises(TypedIOValidationException) as off:
        admit_digest(
            step_order=2,
            needed_calls=5,
            needed_input_tokens=900,
            call_ceiling=None,
            token_ceiling=None,
        )
    with pytest.raises(TypedIOValidationException) as calls:
        admit_digest(
            step_order=2,
            needed_calls=6,
            needed_input_tokens=900,
            call_ceiling=5,
            token_ceiling=None,
        )
    with pytest.raises(TypedIOValidationException) as tokens:
        admit_digest(
            step_order=2,
            needed_calls=5,
            needed_input_tokens=901,
            call_ceiling=5,
            token_ceiling=900,
        )

    assert off.value.code == FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED.value
    assert (
        calls.value.code == FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED.value
    )
    assert tokens.value.code == FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value


def test_call_limits_keep_the_final_calls_and_name_the_ceiling_reached():
    limits = DigestCallLimits(call_ceiling=4, token_ceiling=None, reserved_calls=2)

    assert limits.admit(100)
    assert limits.admit(100)
    assert not limits.admit(100)
    assert limits.refused == CALL_CEILING_REASON

    tokens = DigestCallLimits(call_ceiling=10, token_ceiling=150, reserved_calls=1)
    assert tokens.admit(100)
    assert not tokens.admit(100)
    assert tokens.refused == TOKEN_CEILING_REASON
    assert (tokens.calls, tokens.input_tokens) == (1, 100)


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def test_the_digest_stops_where_the_final_call_reserve_of_the_step_begins():
    limits = digest_time_limits(now=100.0, expires_at=200.0, budget_seconds=120.0)

    assert limits.deadline == 170.0
    assert limits.reduce_reserve_seconds == pytest.approx(17.5)


def test_a_step_already_inside_its_final_reserve_leaves_the_digest_no_window():
    limits = digest_time_limits(now=190.0, expires_at=200.0, budget_seconds=120.0)

    assert limits.deadline < 190.0
    assert limits.reduce_reserve_seconds == 0.0


# --------------------------------------------------------------------------- #
# What each call read
# --------------------------------------------------------------------------- #
def test_a_map_call_is_known_by_its_prompt_and_names_its_source_and_segment():
    keys = {"S1": 1, "S2": 2}
    system = map_prompt("Find dates.", STAGE_DEFAULTS.map_words)

    assert is_map_call(system, instruction="Find dates.", budgets=STAGE_DEFAULTS)
    assert not is_map_call(
        "Merge notes", instruction="Find dates.", budgets=STAGE_DEFAULTS
    )
    assert map_call_target("[S2] Minutes (segment 3 of 4)\n\ntext", keys) == (
        DigestCallInput(
            stage="map", source_indexes=(2,), segment_index=3, segment_count=4
        )
    )
    assert map_call_target("[S7] Unknown (segment 1 of 1)\n\ntext", keys) is None


def test_merges_and_the_final_call_name_the_sources_their_notes_cite():
    keys = {"S1": 1, "S2": 2, "S3": 3}
    notes = "Budget cut [S3]. Agreed by both [S1, S2]. Not a key [S9] or [x]."

    assert cited_sources(notes, keys) == (1, 2, 3)
    assert reduce_call(notes, keys).source_indexes == (1, 2, 3)
    assert final_call("no citations", keys) == DigestCallInput(
        stage="final", source_indexes=()
    )


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #
def _sources_and_plan(segment_words: int = 40):
    first = " ".join(f"a{i}" for i in range(100))
    second = " ".join(f"b{i}" for i in range(30))
    question = f"{first}\n\n{second}"
    sources = partition_digest_sources(
        question, [candidate("first", first), candidate("second", second)]
    )
    budgets = replace(
        STAGE_DEFAULTS, segment_tokens=segment_words, reduce_input_tokens=10_000
    )
    plan = without_direct_path(
        plan_segments([source.item() for source in sources], budgets, words)
    )
    return sources, plan, budgets


def map_record(
    source: int, segment: int, count: int, outcome: str = "ok"
) -> DigestCallRecord:
    return DigestCallRecord(
        call=DigestCallInput(
            stage="map",
            source_indexes=(source,),
            segment_index=segment,
            segment_count=count,
        ),
        outcome=outcome,  # type: ignore[arg-type]
        num_tokens_input=None if outcome == "failed" else 10,
        num_tokens_output=None if outcome == "failed" else 2,
    )


def test_coverage_is_complete_when_every_planned_segment_came_back():
    sources, plan, budgets = _sources_and_plan()
    first_segments = len(plan.items[0].segments)
    records = [
        *(map_record(1, n, first_segments) for n in range(1, first_segments + 1)),
        map_record(2, 1, 1),
        DigestCallRecord(
            call=reduce_call("[S1]", {"S1": 1}),
            outcome="ok",
            num_tokens_input=7,
            num_tokens_output=3,
        ),
    ]
    result = DigestResult(
        output="Notes:\n\n[S1] x\n\n[S2] y",
        coverage="complete",
        item_progress={
            "S1": ItemProgress(planned=first_segments, processed=first_segments),
            "S2": ItemProgress(planned=1, processed=1),
        },
    )

    coverage = build_coverage(
        result=result,
        sources=sources,
        plan=plan,
        budgets=budgets,
        calls=records,
        notes=result.output,
    )

    assert coverage.coverage == "complete"
    assert coverage.left_out == ()
    assert all(source.complete for source in coverage.sources)
    assert coverage.map_calls == first_segments + 1
    assert coverage.reduce_calls == 1
    assert coverage.num_tokens_input == 10 * (first_segments + 1) + 7
    assert coverage.num_tokens_output == 2 * (first_segments + 1) + 3
    assert coverage.notes_bytes == len(result.output.encode())
    assert coverage.segments_read == coverage.segments_planned


def test_a_failed_cut_or_unsent_segment_makes_its_source_partial_and_named():
    sources, plan, budgets = _sources_and_plan()
    count = len(plan.items[0].segments)
    assert count >= 3
    records = [
        map_record(1, 1, count, "failed"),
        map_record(1, 2, count, "cut"),
        *(map_record(1, n, count) for n in range(4, count + 1)),
        map_record(2, 1, 1),
    ]
    result = DigestResult(
        output="Notes:\n\n[S1] x",
        coverage="partial",
        item_progress={
            "S1": ItemProgress(planned=count, processed=count - 2, failed=1, cut=1),
            "S2": ItemProgress(planned=1, processed=1),
        },
        reasons=["notes cut short", "failed segments"],
    )

    coverage = build_coverage(
        result=result, sources=sources, plan=plan, budgets=budgets, calls=records
    )

    first, second = coverage.sources
    assert coverage.coverage == "partial"
    assert coverage.left_out == ("S1",)
    assert (first.segments_failed, first.segments_cut, first.segments_not_read) == (
        (1,),
        (2,),
        (3,),
    )
    assert 2 in first.segments_read and not first.complete
    assert second.complete
    assert coverage.failed_calls == 1
    assert describe_left_out(coverage) == f"S1 'first' (segments 1-3 of {count})"


def test_a_ceiling_reason_of_the_runtime_keeps_complete_core_coverage_partial():
    sources, plan, budgets = _sources_and_plan()
    count = len(plan.items[0].segments)
    records = [
        *(map_record(1, n, count) for n in range(1, count + 1)),
        map_record(2, 1, 1),
    ]
    result = DigestResult(
        output="Notes",
        coverage="complete",
        item_progress={
            "S1": ItemProgress(planned=count, processed=count),
            "S2": ItemProgress(planned=1, processed=1),
        },
    )

    coverage = build_coverage(
        result=result,
        sources=sources,
        plan=plan,
        budgets=budgets,
        calls=records,
        extra_reasons=(CALL_CEILING_REASON,),
    )

    assert coverage.coverage == "partial"
    assert coverage.reasons == (CALL_CEILING_REASON,)


async def test_notes_left_out_of_the_final_request_are_reported_as_partial():
    sources, plan, budgets = _sources_and_plan()
    keys = {source.key: source.index for source in sources}
    records: list[DigestCallRecord] = []

    async def complete(system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        call = map_call_target(user, keys) if "take notes" in system else None
        call = call or reduce_call(user, keys)
        records.append(
            DigestCallRecord(
                call=call,
                outcome="ok",
                num_tokens_input=words(user),
                num_tokens_output=50,
            )
        )
        # Notes and merges that never shrink force the core to leave some out.
        return " ".join(["note"] * 400), Usage(words(user), 400)

    async def capture(system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        return user, Usage()

    tight = replace(budgets, reduce_input_tokens=500)
    result = await run_digest(
        plan,
        complete,
        instruction="Find everything.",
        budgets=tight,
        count=words,
        map_batch=1,
        complete_map=complete,
        complete_final=capture,
    )

    coverage = build_coverage(
        result=result, sources=sources, plan=plan, budgets=tight, calls=records
    )

    assert coverage.coverage == "partial"
    assert "excluded at reduce" in coverage.reasons
    excluded = [source for source in coverage.sources if source.excluded_at_reduce]
    assert excluded and all(not source.complete for source in excluded)
    assert set(coverage.left_out) == {source.key for source in excluded}


async def test_a_digest_past_its_deadline_reads_no_further_and_is_partial():
    sources, plan, budgets = _sources_and_plan()
    keys = {source.key: source.index for source in sources}
    clock = [0.0]
    records: list[DigestCallRecord] = []

    async def complete(system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        call = map_call_target(user, keys) or reduce_call(user, keys)
        records.append(
            DigestCallRecord(
                call=call, outcome="ok", num_tokens_input=1, num_tokens_output=1
            )
        )
        clock[0] += 10.0
        return "Date: unknown\nfact", Usage(1, 1)

    async def capture(system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        return user, Usage()

    limits = digest_time_limits(now=0.0, expires_at=40.0, budget_seconds=40.0)
    result = await run_digest(
        plan,
        complete,
        instruction="Find everything.",
        budgets=budgets,
        count=words,
        deadline=limits.deadline,
        reduce_reserve_seconds=limits.reduce_reserve_seconds,
        map_batch=1,
        now=lambda: clock[0],
        complete_map=complete,
        complete_final=capture,
    )

    coverage = build_coverage(
        result=result, sources=sources, plan=plan, budgets=budgets, calls=records
    )

    assert clock[0] <= limits.deadline + 10.0
    assert coverage.coverage == "partial"
    assert "deadline" in coverage.reasons
    assert any(source.segments_not_read for source in coverage.sources)
    assert coverage.segments_read < coverage.segments_planned


# --------------------------------------------------------------------------- #
# Partial coverage policy
# --------------------------------------------------------------------------- #
def _coverage(state: str, *, read: int):
    sources, plan, budgets = _sources_and_plan()
    count = len(plan.items[0].segments)
    records = [map_record(1, n, count) for n in range(1, read + 1)]
    result = DigestResult(
        output="Notes",
        coverage=state,  # type: ignore[arg-type]
        item_progress={
            "S1": ItemProgress(planned=count, processed=read),
            "S2": ItemProgress(planned=1, processed=0),
        },
        reasons=["deadline"] if state != "complete" else [],
    )
    return build_coverage(
        result=result, sources=sources, plan=plan, budgets=budgets, calls=records
    )


def test_complete_coverage_is_accepted_with_or_without_review():
    sources, plan, budgets = _sources_and_plan()
    count = len(plan.items[0].segments)
    complete = build_coverage(
        result=DigestResult(
            output="Notes",
            coverage="complete",
            item_progress={
                "S1": ItemProgress(planned=count, processed=count),
                "S2": ItemProgress(planned=1, processed=1),
            },
        ),
        sources=sources,
        plan=plan,
        budgets=budgets,
        calls=[
            *(map_record(1, n, count) for n in range(1, count + 1)),
            map_record(2, 1, 1),
        ],
    )

    assert partial_coverage_outcome(complete, review_configured=False) == "accept"
    assert partial_coverage_outcome(complete, review_configured=True) == "accept"


def test_partial_coverage_fails_the_step_unless_its_review_can_judge_an_answer():
    partial = _coverage("partial", read=2)
    nothing_read = _coverage("partial", read=0)

    assert partial_coverage_outcome(partial, review_configured=False) == "fail"
    assert partial_coverage_outcome(partial, review_configured=True) == "review"
    assert partial_coverage_outcome(nothing_read, review_configured=True) == "fail"


def test_the_partial_coverage_failure_carries_its_code_reasons_and_progress():
    partial = _coverage("partial", read=2)

    error = partial_coverage_error(step_order=3, coverage=partial)

    assert error.code == FlowApiErrorCode.LONG_MATERIAL_PARTIAL_COVERAGE.value
    assert "deadline" in str(error)
    assert "S1 'first'" in str(error)
    assert error.context == {
        "completed_items": 2,
        "total_items": partial.segments_planned,
    }
