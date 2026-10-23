"""The ``duplicate_read`` suggestion: when a step's model receives the same
earlier step twice, how it is graded, how it is fixed, and that its
fingerprint follows its premise and nothing else."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from eneo.flows.domain.flow_suggestions import (
    MAX_FLOW_SUGGESTIONS,
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
    suggestion_fingerprint,
)
from eneo.flows.enums import FlowInputSource, FlowOutputMode

_IDS = [UUID(int=index) for index in range(1, 80)]


def _step(
    order: int,
    *,
    input_source: FlowInputSource = FlowInputSource.PREVIOUS_STEP,
    input_bindings: Mapping[str, object] | None = None,
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH,
    prompt_text: str | None = None,
    user_description: str | None = None,
) -> SuggestionStep:
    return SuggestionStep(
        id=_IDS[order],
        step_order=order,
        user_description=user_description or f"Steg {order}",
        input_source=FlowInputSource.FLOW_INPUT if order == 1 else input_source,
        input_type="text",
        input_bindings=input_bindings,
        input_config=None,
        output_mode=output_mode,
        output_type="text",
        output_contract=None,
        output_config=None,
        prompt_text=prompt_text,
        assistant_id=uuid4(),
    )


def _analyze(steps: list[SuggestionStep]) -> tuple[FlowSuggestion, ...]:
    return analyze_flow(SuggestionFlow(steps=steps))


def _duplicates(suggestions: tuple[FlowSuggestion, ...]) -> list[FlowSuggestion]:
    return [s for s in suggestions if s.code is FlowSuggestionCode.DUPLICATE_READ]


def _only(suggestions: tuple[FlowSuggestion, ...]) -> FlowSuggestion:
    """The one ``duplicate_read`` of a draft; other rules may fire on the
    same fixture and are tested in their own files."""
    duplicates = _duplicates(suggestions)
    assert len(duplicates) == 1, suggestions
    return duplicates[0]


def test_previous_step_and_a_prompt_read_of_that_step_is_a_duplicate() -> None:
    suggestion = _only(
        _analyze(
            [_step(1), _step(2, prompt_text="Sammanfatta.\n{{ step_1.output.text }}")]
        )
    )

    assert suggestion.code is FlowSuggestionCode.DUPLICATE_READ
    assert suggestion.steps == (_IDS[2], _IDS[1])
    assert suggestion.impact.basis == "definition"
    assert suggestion.impact.level == "high"
    assert suggestion.fix.kind == "patch"
    assert suggestion.params == {
        "producer_step_order": 1,
        "producer_step_id": str(_IDS[1]),
        "contained": False,
        "redundant_reads": [1],
        "reads": [
            {"channel": "input", "site": "input_source", "selector": []},
            {
                "channel": "prompt",
                "site": "assistant_prompt:step_1.output.text",
                "selector": [],
            },
        ],
    }
    assert suggestion.message == (
        "Step 2 reads step 1 twice, as its input (previous_step) and in its "
        "prompt ({{ step_1.output.text }}), so its model receives the same text "
        "twice on every run."
    )


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param([_step(1), _step(2, prompt_text="Sammanfatta.")], id="no-read"),
        pytest.param(
            [_step(1), _step(2), _step(3, prompt_text="{{ step_1.output.text }}")],
            id="prompt-reads-another-step",
        ),
        pytest.param(
            [
                _step(1),
                _step(
                    2,
                    output_mode=FlowOutputMode.COPY_INPUT,
                    prompt_text="{{ step_1.output.text }}",
                ),
            ],
            id="no-model-reads-the-prompt",
        ),
        pytest.param(
            [
                _step(1),
                _step(
                    2,
                    input_bindings={"question": "Svara."},
                    prompt_text=(
                        "{{ step_1.output.structured.a }} {{ step_1.output.structured.b }}"
                    ),
                ),
            ],
            id="two-different-fields",
        ),
        pytest.param(
            [
                _step(1),
                _step(2),
                _step(
                    3,
                    input_bindings={"question": "{{ step_1.output.text }}"},
                    prompt_text="{{ step_2.output.text }}",
                ),
            ],
            id="question-and-prompt-read-different-steps",
        ),
    ],
)
def test_no_duplicate_without_a_second_read_of_the_same_step(
    steps: list[SuggestionStep],
) -> None:
    assert _duplicates(_analyze(steps)) == []


def test_all_previous_steps_and_a_prompt_read_is_a_medium_duplicate() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(2),
                _step(
                    3,
                    input_source=FlowInputSource.ALL_PREVIOUS_STEPS,
                    prompt_text="Bakgrund: {{ step_1.output.text }}",
                ),
            ]
        )
    )

    assert suggestion.impact.level == "medium"
    assert suggestion.params["producer_step_order"] == 1
    assert suggestion.fix.kind == "assisted"
    assert "as its input (all_previous_steps)" in suggestion.message


def test_a_question_and_the_prompt_reading_the_same_step_is_a_duplicate() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(2),
                _step(
                    3,
                    input_bindings={"question": "{{ step_1.output.text }}"},
                    prompt_text="Bakgrund: {{ step_1.output.text }}",
                ),
            ]
        )
    )

    assert suggestion.impact.level == "high"
    assert [read["site"] for read in suggestion.params["reads"]] == [
        "input_bindings.question",
        "assistant_prompt:step_1.output.text",
    ]
    # The prompt read is inline, so the fix needs judgement.
    assert suggestion.fix.kind == "assisted"


def test_two_prompt_reads_of_the_same_whole_text_are_a_duplicate() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    input_source=FlowInputSource.FLOW_INPUT,
                    input_bindings={"question": "Svara."},
                    prompt_text="Text: {{ step_1.output.text }}\n{{ step_1.output }}",
                ),
            ]
        )
    )

    assert suggestion.impact.level == "high"
    assert [read["channel"] for read in suggestion.params["reads"]] == [
        "prompt",
        "prompt",
    ]
    # The second read stands alone on its line.
    assert suggestion.fix.kind == "patch"


def test_a_field_read_next_to_the_whole_text_is_contained() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(2, prompt_text="Titel: {{ step_1.output.structured.title }}"),
            ]
        )
    )

    assert suggestion.params["contained"] is True
    assert suggestion.impact.level == "low"
    assert suggestion.params["reads"][1]["selector"] == ["structured", "title"]
    assert suggestion.message == (
        "Step 2 reads step 1 as its input (previous_step) and in its prompt "
        "({{ step_1.output.structured.title }}), where the narrower read is part "
        "of what the whole read already carries."
    )


def test_a_field_in_the_input_next_to_the_whole_text_in_the_prompt_is_the_redundant_read() -> (
    None
):
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    input_bindings={"question": "{{ step_1.output.structured.title }}"},
                    prompt_text="{{ step_1.output.text }}",
                ),
            ]
        )
    )

    assert suggestion.params["contained"] is True
    # The prompt carries the whole text; removing it would drop data.
    assert suggestion.params["redundant_reads"] == [0]
    assert suggestion.params["reads"][0]["site"] == "input_bindings.question"


def test_the_whole_input_next_to_a_field_in_the_prompt_keeps_the_input() -> None:
    suggestion = _only(
        _analyze(
            [_step(1), _step(2, prompt_text="{{ step_1.output.structured.title }}")]
        )
    )

    assert suggestion.params["contained"] is True
    assert suggestion.params["redundant_reads"] == [1]
    assert suggestion.params["reads"][1]["channel"] == "prompt"


def test_every_narrower_read_a_wider_read_contains_is_redundant() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    prompt_text=(
                        "{{ step_1.output.structured.a }}\n"
                        "{{ step_1.output.structured.b }}"
                    ),
                ),
            ]
        )
    )

    assert suggestion.params["redundant_reads"] == [1, 2]


def test_a_path_under_a_structured_source_ref_is_contained() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    input_bindings={
                        "source_refs": [{"step_ref": "step_1", "output": "structured"}]
                    },
                    prompt_text="{{ step_1.output.structured.a.b }}",
                ),
            ]
        )
    )

    assert suggestion.params["contained"] is True
    assert suggestion.impact.level == "low"


def test_the_question_being_exactly_the_expression_is_patchable() -> None:
    suggestion = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    input_bindings={
                        "question": "  {{ step_1.output.text }} ",
                        "source_refs": [{"step_ref": "step_1", "output": "text"}],
                    },
                ),
            ]
        )
    )

    # Both reads are in the input channel; the source ref is the later one
    # and a list entry, so the fix is mechanical.
    assert [read["site"] for read in suggestion.params["reads"]] == [
        "input_bindings.question",
        "input_bindings.source_refs[0]",
    ]
    assert suggestion.fix.kind == "patch"


def test_an_inline_prompt_read_needs_an_assisted_fix() -> None:
    suggestion = _only(
        _analyze(
            [_step(1), _step(2, prompt_text="Bakgrund: {{ step_1.output.text }} slut")]
        )
    )

    assert suggestion.fix.kind == "assisted"


def _three_steps(
    *, third_name: str = "Steg 3", prompt: str = "{{ step_1.output.text }}"
) -> list[SuggestionStep]:
    return [
        _step(1),
        _step(2, prompt_text=prompt),
        _step(3, user_description=third_name),
    ]


def test_the_fingerprint_holds_under_unrelated_edits() -> None:
    before = _only(_analyze(_three_steps()))

    renamed = _only(_analyze(_three_steps(third_name="Annat namn")))
    reworded = _only(
        _analyze(_three_steps(prompt="Ny text.\n{{ step_1.output.text }}\nMer."))
    )

    assert renamed.fingerprint == before.fingerprint
    assert reworded.fingerprint == before.fingerprint


def test_the_fingerprint_follows_the_premise() -> None:
    before = _only(_analyze(_three_steps()))

    assert _duplicates(_analyze(_three_steps(prompt="Ingen läsning."))) == []
    # The same producer reached another way is another premise.
    through_question = _only(
        _analyze(
            [
                _step(1),
                _step(
                    2,
                    input_bindings={"question": "{{ step_1.output.text }}"},
                    prompt_text="{{ step_1.output.text }}",
                ),
                _step(3),
            ]
        )
    )
    assert through_question.fingerprint != before.fingerprint
    assert before.fingerprint == suggestion_fingerprint(
        FlowSuggestionCode.DUPLICATE_READ,
        [_IDS[2], _IDS[1]],
        {
            "producer_step_order": 1,
            "sites": [
                {"channel": "input", "site": "input_source"},
                {"channel": "prompt", "site": "assistant_prompt:step_1.output.text"},
            ],
        },
    )


def test_suggestions_are_ordered_by_level_then_step_order() -> None:
    suggestions = _duplicates(
        _analyze(
            [
                _step(1),
                _step(2, prompt_text="{{ step_1.output.structured.a }}"),
                _step(3, prompt_text="{{ step_2.output.text }}"),
                _step(
                    4,
                    input_source=FlowInputSource.ALL_PREVIOUS_STEPS,
                    prompt_text="{{ step_1.output.text }}",
                ),
                _step(5, prompt_text="{{ step_4.output.text }}"),
            ]
        )
    )

    assert [(s.impact.level, s.steps[0]) for s in suggestions] == [
        ("high", _IDS[3]),
        ("high", _IDS[5]),
        ("medium", _IDS[4]),
        ("low", _IDS[2]),
    ]


def test_at_most_fifty_suggestions_are_returned() -> None:
    steps = [_step(1)] + [
        _step(order, prompt_text=f"{{{{ step_{order - 1}.output.text }}}}")
        for order in range(2, MAX_FLOW_SUGGESTIONS + 5)
    ]

    suggestions = _analyze(steps)

    assert len(suggestions) == MAX_FLOW_SUGGESTIONS
    assert [s.steps[0] for s in suggestions] == [
        _IDS[order] for order in range(2, MAX_FLOW_SUGGESTIONS + 2)
    ]
