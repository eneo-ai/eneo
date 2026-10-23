"""The editor updates that fix a suggestion: what each builder writes, and
that every body is an editor update once its revision is added."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from eneo.flows.api.flow_models import FlowEditorUpdateRequest
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    SuggestionFlow,
    SuggestionStep,
)
from eneo.flows.domain.flow_suggestion_patches import (
    contract_declares_path,
    contract_without_fields_patch,
    form_without_field_patch,
    prompt_without_line,
    relay_patch,
    remove_reads_patch,
    remove_step_patch,
)
from eneo.flows.step_lineage import StepRead

_IDS = [UUID(int=index) for index in range(1, 20)]
_MAPPING = {"Steg 1": 1, "Steg 2": 2, "Steg 3": 3}
_CONTRACT = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    "required": ["title", "body"],
}


def _step(order: int, **columns: Any) -> SuggestionStep:
    values: dict[str, Any] = {
        "id": _IDS[order],
        "step_order": order,
        "user_description": f"Steg {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "input_bindings": None,
        "input_config": None,
        "output_mode": "pass_through",
        "output_type": "text",
        "output_contract": None,
        "output_config": None,
        "prompt_text": "Gör så här.",
        "assistant_id": UUID(int=100 + order),
        "prompt_description": "Instruktion",
    }
    return SuggestionStep(**{**values, **columns})


def _validates(patch: dict[str, Any] | None) -> FlowEditorUpdateRequest:
    assert patch is not None
    return FlowEditorUpdateRequest.model_validate({**patch, "expected_revision": 4})


_PROMPT_READ = StepRead("prompt", 1, (), "assistant_prompt:step_1.output.text")


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Sammanfatta.\n{{ step_1.output.text }}", "Sammanfatta."),
        ("Sammanfatta.\n{{ step_1.output.text }}\n", "Sammanfatta.\n"),
        ("A\n\n{{ step_1.output.text }}\n\nB", "A\n\nB"),
        ("{{ step_1.output.text }}\n\nB", "B"),
        ("A\n\n  {{step_1.output.text}}  ", "A"),
        ("A\r\n{{ step_1.output.text }}\r\nB", "A\r\nB"),
    ],
)
def test_a_standalone_prompt_line_goes_with_one_blank_line(
    prompt: str, expected: str
) -> None:
    assert prompt_without_line(prompt, "step_1.output.text") == expected


def test_no_line_is_removed_when_the_read_is_inline() -> None:
    assert (
        prompt_without_line("Läs {{ step_1.output.text }} nu", "step_1.output.text")
        is None
    )


def test_a_redundant_prompt_read_is_an_assistant_change_for_the_step() -> None:
    step = _step(2, prompt_text="Sammanfatta.\n{{ step_1.output.text }}")

    patch = remove_reads_patch(step, [_PROMPT_READ], step_ref_mapping=_MAPPING)

    assert patch == {
        "definition": {},
        "assistants": [
            {
                "assistant_id": str(UUID(int=102)),
                "step_id": str(_IDS[2]),
                "changes": {
                    "prompt": {"text": "Sammanfatta.", "description": "Instruktion"}
                },
            }
        ],
    }
    update = _validates(patch)
    assert update.assistants[0].step_id == _IDS[2]


def test_one_of_two_prompt_reads_of_the_same_expression_goes() -> None:
    step = _step(
        2, prompt_text="{{ step_1.output.text }}\nOch: {{ step_1.output.text }}"
    )

    patch = remove_reads_patch(step, [_PROMPT_READ], step_ref_mapping=_MAPPING)

    assert patch is not None
    assert patch["assistants"][0]["changes"]["prompt"]["text"] == (
        "Och: {{ step_1.output.text }}"
    )


def test_a_redundant_source_ref_is_removed_from_the_underlag() -> None:
    step = _step(
        2,
        input_bindings={
            "question": "{{ step_1.output.text }}",
            "source_refs": [
                {"step_ref": "step_1", "output": "text"},
                {"step_ref": "step_1", "output": "text", "label": "Igen"},
            ],
        },
    )
    read = StepRead("input", 1, (), "input_bindings.source_refs[1]")

    patch = remove_reads_patch(step, [read], step_ref_mapping=_MAPPING)

    assert patch is not None
    assert patch["step_edits"] == [
        {
            "step_id": str(_IDS[2]),
            "changes": {
                "input_bindings": {
                    "question": "{{ step_1.output.text }}",
                    "source_refs": [{"step_ref": "step_1", "output": "text"}],
                }
            },
        }
    ]
    _validates(patch)


def test_a_question_that_is_the_read_is_removed_while_source_refs_remain() -> None:
    step = _step(
        2,
        input_bindings={
            "question": "{{ step_1.output.structured.title }}",
            "source_refs": [{"step_ref": "step_1", "output": "structured"}],
        },
    )
    read = StepRead("input", 1, ("structured", "title"), "input_bindings.question")

    patch = remove_reads_patch(step, [read], step_ref_mapping=_MAPPING)

    assert patch is not None
    assert patch["step_edits"][0]["changes"]["input_bindings"] == {
        "source_refs": [{"step_ref": "step_1", "output": "structured"}]
    }
    _validates(patch)


def test_emptying_the_underlag_is_not_a_patch() -> None:
    # Without underlag the step would read its input_source instead.
    step = _step(
        2,
        input_source="flow_input",
        input_bindings={"question": "{{ step_1.output.structured.title }}"},
        prompt_text="{{ step_1.output.text }}",
    )
    read = StepRead("input", 1, ("structured", "title"), "input_bindings.question")

    assert remove_reads_patch(step, [read], step_ref_mapping=_MAPPING) is None


def test_the_contract_patch_drops_the_fields_and_their_requirement() -> None:
    step = _step(1, output_type="json", output_contract=_CONTRACT)

    patch = contract_without_fields_patch(step, ["body"])

    assert patch is not None
    assert patch["step_edits"][0]["changes"]["output_contract"] == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    _validates(patch)


def test_the_remove_step_patch_is_the_order_without_the_step() -> None:
    steps = [_step(1), _step(2), _step(3)]

    update = _validates(remove_step_patch(steps, steps[1]))

    assert [slot.step_id for slot in update.step_order or []] == [_IDS[1], _IDS[3]]


def test_the_form_patch_copies_the_metadata_without_the_field() -> None:
    metadata = {
        "wizard": {"transcription_enabled": True},
        "form_schema": {
            "fields": [
                {"name": "kommun", "type": "text", "order": 1},
                {"name": " ärende ", "type": "text", "order": 2},
            ]
        },
    }

    patch = form_without_field_patch(metadata, "ärende")

    assert patch == {
        "definition": {
            "metadata_json": {
                "wizard": {"transcription_enabled": True},
                "form_schema": {
                    "fields": [{"name": "kommun", "type": "text", "order": 1}]
                },
            }
        }
    }
    assert metadata["form_schema"]["fields"][1]["name"] == " ärende "
    _validates(patch)
    assert form_without_field_patch(metadata, "saknas") is None


def test_the_relay_patch_validates_as_one_editor_update() -> None:
    draft = DraftReads.of(
        SuggestionFlow(
            steps=[
                _step(1),
                _step(2, output_mode="compose_text", prompt_text=None),
                _step(3, prompt_text="{{ föregående_steg }}"),
                _step(
                    4,
                    input_source="flow_input",
                    input_bindings={
                        "source_refs": [
                            {"step_ref": "Steg 2", "output": "text"},
                            {"step_ref": "step_3", "output": "text"},
                        ]
                    },
                ),
            ]
        )
    )

    relay = draft.step_at(2)
    assert relay is not None
    update = _validates(relay_patch(draft, relay, 1))

    # föregående_steg still names step 1 once the relay is gone.
    assert update.assistants == []
    (edit,) = update.step_edits
    assert edit.changes.input_bindings == {
        "source_refs": [
            {"step_ref": "step_1", "output": "text"},
            {"step_ref": "step_2", "output": "text"},
        ]
    }
    assert [slot.step_id for slot in update.step_order or []] == [
        _IDS[1],
        _IDS[3],
        _IDS[4],
    ]


@pytest.mark.parametrize(
    ("path", "declared"),
    [
        (("title",), True),
        (("body", "text"), True),
        (("body", "other"), False),
        (("missing",), False),
        (("title", "deeper"), False),
    ],
)
def test_a_contract_declares_the_paths_its_properties_name(
    path: tuple[str, ...], declared: bool
) -> None:
    assert contract_declares_path(_CONTRACT, path) is declared
