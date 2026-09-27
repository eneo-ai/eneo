"""A saved read keeps naming the step it read, or the edit is refused.

A saved step names its producers by runtime alias (`step_N`, its saved order).
When an edit removes that producer, or moves it after the reader, the alias
would name whichever step now stands at position N; validation reads it that
way. The edit compiler refuses such an edit and names every stale read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_edit_compiler as edit_compiler
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    EditCompilationResult,
    compile_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_MESSAGE_LENGTH,
    MAX_DIAGNOSTIC_NAME_LENGTH,
    BoundedListing,
    display_value,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowStep

SEEDS = Path(__file__).resolve().parents[4] / "scripts/fixtures/ai_builder_battle"
SUMMARY = "{{ step_2.output.text }}"


def _step(
    order: int,
    name: str,
    *,
    instructions: str = "Gör uppgiften.",
    **fields: Any,
) -> tuple[FlowStep, str]:
    step = FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=order,
        user_description=name,
        input_source=fields.pop("input_source", "previous_step"),
        input_type="text",
        output_mode=fields.pop("output_mode", "pass_through"),
        output_type=fields.pop("output_type", "text"),
        **fields,
    )
    return step, instructions


def _flow(**writer: Any) -> list[tuple[FlowStep, str]]:
    """Read, summarize, assess, write: the writer reads the summary (step 2)."""

    return [
        _step(1, "Läs ärendet", input_source="flow_input"),
        _step(2, "Sammanfatta"),
        _step(3, "Bedöm"),
        _step(4, "Skriv beslut", **writer),
    ]


def _compile(
    flow: list[tuple[FlowStep, str]],
    order: tuple[int, ...],
    *,
    removed: tuple[int, ...] = (),
    **options: Any,
) -> EditCompilationResult:
    steps = [step for step, _ in flow]
    return compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Edit.",
            steps=[
                ModifyExistingStep(existing_step_ref=f"existing_step_{o}")
                for o in order
            ],
            removed_existing_step_refs=frozenset(f"existing_step_{o}" for o in removed),
        ),
        steps,
        base_flow_revision=1,
        assistant_snapshots={
            step.assistant_id: AssistantAuthoringSnapshot(instructions=instructions)
            for step, instructions in flow
        },
        **options,
    )


def _seed_flow(name: str) -> list[tuple[FlowStep, str]]:
    raw = json.loads((SEEDS / name).read_text())
    return [
        _step(
            order,
            step["name"],
            instructions=step["instructions"],
            input_source=step["input_source"],
            output_mode=step["output_mode"],
            output_type=step["output_type"],
            input_bindings=step.get("input_bindings"),
            output_contract=step.get("output_contract"),
        )
        for order, step in enumerate(raw["steps"], 1)
    ]


def _refused(*args: Any, **kwargs: Any) -> str:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _compile(*args, **kwargs)
    assert exc_info.value.code is AIBuilderErrorCode.INVALID_PLAN_STEP_REF
    return str(exc_info.value)


READS_OF_THE_SUMMARY = {
    "source_refs": {
        "input_bindings": {
            "source_refs": [
                {"step_ref": "step_2", "output": "text", "label": "Sammanfattning"}
            ]
        }
    },
    "question": {"input_bindings": {"question": f"Sammanfattning: {SUMMARY}"}},
    "instructions": {"instructions": f"Utgå från sammanfattningen: {SUMMARY}"},
    "output_config": {
        "output_mode": "template_fill",
        "output_type": "docx",
        "output_config": {"bindings": {"sammanfattning": SUMMARY}},
    },
}


@pytest.mark.parametrize("site", list(READS_OF_THE_SUMMARY))
def test_a_kept_read_of_a_removed_step_is_refused_at_every_site(site: str) -> None:
    message = _refused(_flow(**READS_OF_THE_SUMMARY[site]), (1, 3, 4), removed=(2,))

    assert "Skriv beslut" in message
    assert site in message
    assert "step_2.output.text" in message
    assert '"Sammanfatta" is removed by this edit' in message


@pytest.mark.parametrize("site", ["source_refs", "question"])
def test_a_kept_read_of_a_step_moved_after_it_is_refused(site: str) -> None:
    message = _refused(_flow(**READS_OF_THE_SUMMARY[site]), (1, 3, 4, 2))

    assert site in message
    assert '"Sammanfatta" is moved after it' in message


@pytest.mark.parametrize("site", ["source_refs", "question"])
def test_a_kept_read_of_a_step_moved_but_still_before_it_follows_the_step(
    site: str,
) -> None:
    result = _compile(_flow(**READS_OF_THE_SUMMARY[site]), (1, 3, 2, 4))

    plan_ref = {s.existing_step_ref: s.plan_step_ref for s in result.spec.steps}
    writer = result.spec.steps[3]
    assert writer.input_bindings is not None
    assert json.dumps(writer.input_bindings).count(plan_ref["existing_step_2"]) == 1
    assert "step_2" not in json.dumps(writer.input_bindings)


def test_an_attached_template_judges_its_own_placeholder_mappings() -> None:
    # The attachment contract refuses a retained placeholder whose producer is
    # gone, by placeholder name; the alias guard leaves that map to it.
    flow = _flow(**READS_OF_THE_SUMMARY["output_config"])

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _compile(
            flow,
            (1, 3, 4),
            removed=(2,),
            selected_template_count=1,
            selected_template_placeholders=("sammanfattning",),
        )

    assert "sammanfattning" in str(exc_info.value)


def test_a_placeholder_the_attached_template_drops_is_left_to_that_contract() -> None:
    flow = _flow(**READS_OF_THE_SUMMARY["output_config"])

    # The template contract, not the stale-read guard, answers: nothing in
    # the edited flow produces `beslut` any more.
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _compile(
            flow,
            (1, 3, 4),
            removed=(2,),
            selected_template_count=1,
            selected_template_placeholders=("beslut",),
        )

    assert exc_info.value.failure_code == "template_placeholder_unproduced"


def test_int04_keeping_the_writer_while_its_summary_step_goes_is_refused() -> None:
    # The null-input repair of the captured me_int04 proposal: step 3 kept as
    # saved still reads the removed summary, which would then name step 3.
    message = _refused(_seed_flow("edit_seed_int04.json"), (1, 3), removed=(2,))

    assert '"Sammanfatta betänkandet" is removed by this edit' in message


def test_int01_a_kept_read_is_not_redirected_to_the_step_that_takes_its_place() -> None:
    # Without the guard, step 4's `step_2.arendemening` named old step 3 and
    # the spec validated.
    message = _refused(_seed_flow("edit_seed_int01.json"), (1, 3, 4), removed=(2,))

    assert "step_2.output.structured.arendemening" in message
    assert '"Formulera ärendemening" is removed by this edit' in message


def test_the_refusal_is_bounded_and_shows_only_whole_entries() -> None:
    long_name = "Sammanfatta " + "mycket " * 60
    question = "\n".join(
        "{{ step_2.output.structured.falt_" + str(index) + " }}" for index in range(20)
    )
    flow = _flow(input_bindings={"question": question})
    flow[1] = _step(2, long_name)

    message = _refused(flow, (1, 3, 4), removed=(2,))

    shown = [line for line in message.splitlines() if line.startswith("- ")]
    assert len(message) <= MAX_DIAGNOSTIC_MESSAGE_LENGTH
    assert shown
    assert all(line.endswith("is removed by this edit.") for line in shown)
    assert message.endswith(f"... and {20 - len(shown)} more.")
    assert long_name not in message


def test_a_template_mapping_the_edit_discards_is_not_a_stale_read() -> None:
    # The template step becomes a text step: normalization drops its
    # placeholder mappings, so the one naming the removed step reads nothing.
    flow = _flow(**READS_OF_THE_SUMMARY["output_config"])
    steps = [step for step, _ in flow]

    result = compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Edit.",
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                ModifyExistingStep(existing_step_ref="existing_step_3"),
                ModifyExistingStep(
                    existing_step_ref="existing_step_4", output_type="text"
                ),
            ],
            removed_existing_step_refs=frozenset({"existing_step_2"}),
        ),
        steps,
        base_flow_revision=1,
        assistant_snapshots={
            step.assistant_id: AssistantAuthoringSnapshot(instructions=instructions)
            for step, instructions in flow
        },
    )

    assert result.spec.steps[-1].output_config is None


def test_a_bounded_listing_formats_and_stores_only_what_it_can_show() -> None:
    listing = BoundedListing()
    formatted: list[int] = []

    def entry(index: int) -> str:
        formatted.append(index)
        return f"entry {index}"

    for index in range(20):
        listing.add(lambda index=index: entry(index))

    assert formatted == list(range(8))
    assert listing.entries == [f"entry {index}" for index in range(8)]
    assert listing.total == 20


def test_the_guard_formats_display_values_only_for_the_entries_it_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_display_value(text: str) -> str:
        calls.append(text)
        return display_value(text)

    monkeypatch.setattr(edit_compiler, "display_value", counting_display_value)
    question = "\n".join(
        "{{ step_2.output.structured.falt_" + str(index) + " }}" for index in range(20)
    )

    _refused(_flow(input_bindings={"question": question}), (1, 3, 4), removed=(2,))

    # Four values per kept entry: reader, read, site and producer.
    assert len(calls) == 4 * 8


def test_a_bounded_listing_renders_whole_entries_and_counts_the_rest() -> None:
    listing = BoundedListing()
    for index in range(20):
        listing.add(lambda index=index: f"entry {index} " + "x" * 300 + ".")

    rendered = listing.render("Heading:")

    shown = [line for line in rendered.splitlines() if line.startswith("- ")]
    assert len(rendered) <= MAX_DIAGNOSTIC_MESSAGE_LENGTH
    assert 0 < len(shown) < 8
    assert all(line.endswith("x.") for line in shown)
    assert rendered.endswith(f"... and {20 - len(shown)} more.")


def test_a_saved_name_cannot_forge_a_line_of_the_refusal() -> None:
    forged = 'Sammanfatta\n- Step 99 "fake" reads something \x85\tend'
    flow = _flow(**READS_OF_THE_SUMMARY["source_refs"])
    flow[1] = _step(2, forged)

    message = _refused(flow, (1, 3, 4), removed=(2,))

    assert [line for line in message.splitlines() if line.startswith("- ")] == [
        '- Step 3 "Skriv beslut" reads step_2.output.text in its source_refs; '
        'saved step 2 "Sammanfatta\\n- Step 99 "fake" reads something\\u2028'
        '\\x85\\tend" is removed by this edit.'
    ]


def test_a_display_value_escapes_control_characters_and_is_clipped() -> None:
    assert display_value("a\nb\r\x00\x9f c") == "a\\nb\\r\\x00\\x9f\\u2029c"
    assert display_value("x" * 200) == "x" * MAX_DIAGNOSTIC_NAME_LENGTH


def test_a_display_value_of_a_huge_name_is_cheap_and_ends_on_a_whole_escape() -> None:
    started = time.perf_counter()
    shown = display_value("a" + "\x85" * 10**6)

    assert time.perf_counter() - started < 0.05
    assert shown == "a" + "\\x85" * 19
    assert len(shown) <= MAX_DIAGNOSTIC_NAME_LENGTH
