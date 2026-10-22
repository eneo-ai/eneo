from typing import Any
from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_step_structure import (
    FormFieldChange,
    FormFieldRenameInvalidError,
    FormFieldStillReadError,
    PlacedStep,
    StepReadLostItsProducerError,
    form_field_change,
    restructure_steps,
)
from eneo.flows.domain.flow import FlowStep


def _step(
    order: int,
    *,
    question: str | None = None,
    name: str | None = None,
    **columns: Any,
) -> FlowStep:
    values: dict[str, Any] = {
        "id": uuid4(),
        "assistant_id": uuid4(),
        "step_order": order,
        "user_description": name or f"Step {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "input_bindings": {"question": question} if question is not None else None,
        "output_mode": "pass_through",
        "output_type": "text",
    }
    return FlowStep.model_validate({**values, **columns})


def _renamed(step: FlowStep, name: str | None) -> PlacedStep:
    return PlacedStep(
        step=step.model_copy(update={"user_description": name}),
        saved=step,
        written_columns=frozenset({"user_description"}),
    )


def _kept(*steps: FlowStep) -> list[PlacedStep]:
    return [PlacedStep(step=step, saved=step) for step in steps]


def _question(step: FlowStep) -> str:
    assert step.input_bindings is not None
    return str(step.input_bindings["question"])


def test_reads_follow_their_step_when_another_step_moves_ahead():
    first, second = _step(1), _step(2, question="Sammanfatta {{ step_1.output }}")
    third = _step(3)
    prompts: dict[UUID, str] = {second.assistant_id: "Läs {{step_1.output.text}}."}

    structure = restructure_steps(_kept(third, first, second), prompts=prompts)

    assert [step.step_order for step in structure.steps] == [1, 2, 3]
    assert [step.id for step in structure.steps] == [third.id, first.id, second.id]
    assert _question(structure.steps[2]) == "Sammanfatta {{ step_2.output }}"
    assert structure.changed_prompts == {
        second.assistant_id: "Läs {{step_2.output.text}}."
    }


def test_a_new_step_ahead_of_a_reader_moves_its_read():
    first, second = _step(1), _step(2, question="{{step_1.output}}")
    new = _step(9)

    structure = restructure_steps(
        [PlacedStep(step=new), *_kept(first, second)], prompts={}
    )

    assert structure.steps[0].id == new.id
    assert _question(structure.steps[2]) == "{{step_2.output}}"


def test_removing_a_step_nobody_reads_keeps_every_read():
    first, second = _step(1), _step(2, question="{{step_1.output}}")

    structure = restructure_steps(_kept(first, second), prompts={})

    assert _question(structure.steps[1]) == "{{step_1.output}}"
    assert structure.changed_prompts == {}


def test_removing_a_step_that_is_read_is_refused():
    # Step 2 is the one the change removes.
    first = _step(1)
    third = _step(3, question="{{step_2.output}}")

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(_kept(first, third), prompts={})

    assert refused.value.code == "flow_step_read_lost_producer"
    assert refused.value.context == {
        "step_id": str(third.id),
        "step_order": 3,
        "site": "input_bindings.question",
        "reads_step": 2,
        "reason": "producer_removed",
    }


def test_a_prompt_read_of_a_removed_step_is_refused():
    # Step 2 is the one the change removes.
    first = _step(1)
    third = _step(3)
    prompts = {third.assistant_id: "Utgå från {{ step_2.output }}."}

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(_kept(first, third), prompts=prompts)

    assert (refused.value.context or {})["site"] == "prompt"


def test_moving_a_read_step_after_its_reader_is_refused():
    first, second = _step(1), _step(2, question="{{step_1.output}}")

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(_kept(second, first), prompts={})

    assert (refused.value.context or {})["reason"] == "producer_moved_after_reader"


def test_columns_and_prompts_the_edit_writes_are_taken_as_given():
    # Step 2 is the one the change removes.
    first = _step(1)
    third = _step(3, question="{{step_2.output}}")
    edited = third.model_copy(
        update={"input_bindings": {"question": "{{step_1.output}}"}}
    )
    prompts = {third.assistant_id: "{{step_2.output}}"}

    structure = restructure_steps(
        [
            PlacedStep(step=first, saved=first),
            PlacedStep(
                step=edited, saved=third, written_columns=frozenset({"input_bindings"})
            ),
        ],
        prompts=prompts,
        rewritten_prompts=frozenset({third.assistant_id}),
    )

    assert _question(structure.steps[1]) == "{{step_1.output}}"
    assert structure.changed_prompts == {}


def test_a_dangling_read_that_would_name_a_step_is_refused():
    first, second = _step(1), _step(2, question="{{step_5.output}}")
    new_steps = [PlacedStep(step=_step(10 + index)) for index in range(4)]

    # Kept where it was it still names no step.
    restructure_steps([*_kept(first, second), *new_steps], prompts={})

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(
            [
                PlacedStep(step=first, saved=first),
                *new_steps,
                PlacedStep(step=second, saved=second),
            ],
            prompts={},
        )

    assert (refused.value.context or {})["reason"] == "would_read_another_step"


def test_a_reader_moved_before_the_step_it_reads_is_refused_as_the_one_that_moved():
    first, second, third = _step(1), _step(2), _step(3, question="{{step_2.output}}")

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(_kept(third, first, second), prompts={})

    assert (refused.value.context or {})["reason"] == "reader_moved_before_producer"


# Reads by step name.


def test_reads_of_a_renamed_step_follow_its_new_name_everywhere():
    first = _step(1, name="Fakta")
    second = _step(
        2,
        question="Utgå från {{  Fakta }} och {{Fakta}}.",
        output_mode="template_fill",
        output_config={
            "template_file_id": str(uuid4()),
            "bindings": {"x": "{{ Fakta }}"},
        },
    )
    prompts = {second.assistant_id: "Läs {{ Fakta }} noga."}

    structure = restructure_steps(
        [_renamed(first, "Underlag"), PlacedStep(step=second, saved=second)],
        prompts=prompts,
    )

    reader = structure.steps[1]
    assert _question(reader) == "Utgå från {{  Underlag }} och {{Underlag}}."
    assert reader.output_config is not None
    assert reader.output_config["bindings"] == {"x": "{{ Underlag }}"}
    assert structure.changed_prompts == {
        second.assistant_id: "Läs {{ Underlag }} noga."
    }
    assert structure.causes == frozenset({"step_renamed"})


def test_two_steps_that_swap_names_keep_their_readers():
    first, second = _step(1, name="A"), _step(2, name="B")
    third = _step(3, question="{{ A }} sedan {{ B }}")

    structure = restructure_steps(
        [_renamed(first, "B"), _renamed(second, "A"), *_kept(third)],
        prompts={},
    )

    assert _question(structure.steps[2]) == "{{ B }} sedan {{ A }}"


def test_a_source_ref_by_name_follows_the_rename():
    first = _step(1, name="Fakta")
    second = _step(2, input_bindings={"source_refs": [{"step_ref": "Fakta"}]})

    structure = restructure_steps(
        [_renamed(first, "Underlag"), *_kept(second)], prompts={}
    )

    assert structure.steps[1].input_bindings == {
        "source_refs": [{"step_ref": "Underlag"}]
    }


@pytest.mark.parametrize("new_name", [None, "  ", "Fakta. Kort"])
def test_a_rename_no_read_can_follow_is_refused(new_name: str | None):
    first = _step(1, name="Fakta")
    second = _step(2, name="Skriv")
    prompts = {second.assistant_id: "Utgå från {{ Fakta }}."}

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps([_renamed(first, new_name), *_kept(second)], prompts=prompts)

    assert refused.value.context == {
        "step_id": str(second.id),
        "step_order": 2,
        "site": "prompt",
        "reads_step": 1,
        "reason": "producer_renamed",
        "reads_name": "Fakta",
    }


def test_a_rename_that_hands_a_read_name_to_an_earlier_step_is_refused():
    first, second = _step(1, name="Inledning"), _step(2, name="Fakta")
    third = _step(3, question="{{ Fakta }}")

    # Step 1 takes the name step 3 reads step 2 by, step 2 a new one.
    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps([_renamed(first, "Fakta"), *_kept(second, third)], prompts={})

    assert (refused.value.context or {})["reason"] == "producer_renamed"


def test_removing_a_step_read_by_name_is_refused():
    first, second = _step(1), _step(2, name="Fakta")
    third = _step(3, question="{{ Fakta }}")

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(
            _kept(first, third), prompts={}, saved_steps=[first, second, third]
        )

    context = refused.value.context or {}
    assert context["reason"] == "producer_removed"
    assert context["reads_name"] == "Fakta"


def test_moving_a_step_read_by_name_after_its_reader_is_refused():
    first, second = _step(1, name="Fakta"), _step(2, name="Skriv")
    prompts = {second.assistant_id: "{{ Fakta }}"}

    with pytest.raises(StepReadLostItsProducerError) as refused:
        restructure_steps(_kept(second, first), prompts=prompts)

    assert (refused.value.context or {})["reason"] == "producer_moved_after_reader"


def test_a_dangling_name_may_come_to_name_the_renamed_step():
    first = _step(1, name="Utkast")
    second = _step(2, question="{{ Fakta }}")

    structure = restructure_steps(
        [_renamed(first, "Fakta"), *_kept(second)], prompts={}
    )

    assert _question(structure.steps[1]) == "{{ Fakta }}"


# Reads of run form fields.


def _form(*names: str) -> dict[str, Any]:
    return {
        "form_schema": {"fields": [{"name": name, "type": "text"} for name in names]}
    }


def test_reads_of_a_renamed_form_field_follow_it():
    step = _step(
        1,
        question="{{flow_input.kommun}} {{ flow.input.kommun }} {{ kommun }}",
        output_mode="http_post",
        output_config={
            "url": "https://example.test/{{ flow_input.kommun }}",
            "auth": {"mode": "none"},
        },
    )
    prompts = {step.assistant_id: "Kommun: {{kommun}}."}
    change = form_field_change(
        saved_metadata=_form("kommun"),
        metadata=_form("ort"),
        renames={"kommun": "ort"},
    )

    structure = restructure_steps(_kept(step), prompts=prompts, form_fields=change)

    saved = structure.steps[0]
    assert _question(saved) == "{{flow_input.ort}} {{ flow.input.ort }} {{ ort }}"
    assert saved.output_config is not None
    assert saved.output_config["url"] == "https://example.test/{{ flow_input.ort }}"
    assert structure.changed_prompts == {step.assistant_id: "Kommun: {{ort}}."}
    assert structure.causes == frozenset({"form_field_renamed"})


def test_a_bare_read_of_a_field_renamed_to_a_reserved_name_reads_it_through_flow_input():
    step = _step(1, question="{{ kommun }}")
    change = FormFieldChange(saved=frozenset({"kommun"}), renamed={"kommun": "datum"})

    structure = restructure_steps(_kept(step), prompts={}, form_fields=change)

    assert _question(structure.steps[0]) == "{{ flow_input.datum }}"


def test_removing_a_form_field_that_steps_read_is_refused_naming_them():
    first = _step(1, question="{{ flow_input.kommun }}")
    second = _step(2, name="Skriv")
    prompts = {second.assistant_id: "{{ kommun }}"}
    change = form_field_change(saved_metadata=_form("kommun"), metadata=_form())

    with pytest.raises(FormFieldStillReadError) as refused:
        restructure_steps(_kept(first, second), prompts=prompts, form_fields=change)

    assert refused.value.code == "flow_form_field_still_read"
    assert refused.value.context == {
        "fields": ["kommun"],
        "readers": [
            {
                "field": "kommun",
                "step_id": str(first.id),
                "step_order": 1,
                "site": "input_bindings.question",
            },
            {
                "field": "kommun",
                "step_id": str(second.id),
                "step_order": 2,
                "site": "prompt",
            },
        ],
    }


def test_removing_a_form_field_nobody_reads_is_allowed():
    step = _step(1, question="{{ flow_input.namn }}")
    change = form_field_change(
        saved_metadata=_form("namn", "kommun"), metadata=_form("namn")
    )

    structure = restructure_steps(_kept(step), prompts={}, form_fields=change)

    assert structure.steps == [step]


@pytest.mark.parametrize(
    ("renames", "saved", "new", "problem"),
    [
        ({"okänt": "ort"}, ("kommun",), ("ort",), "unknown_field"),
        ({"kommun": "ort"}, ("kommun",), ("stad",), "not_in_form"),
        ({"kommun": "ort"}, ("kommun",), ("kommun", "ort"), "still_in_form"),
        ({"kommun": "namn"}, ("kommun", "namn"), ("namn",), "name_taken"),
        ({"a": "c", "b": "c"}, ("a", "b"), ("c",), "renamed_twice"),
    ],
)
def test_a_rename_the_form_does_not_describe_is_refused(
    renames: dict[str, str], saved: tuple[str, ...], new: tuple[str, ...], problem: str
):
    with pytest.raises(FormFieldRenameInvalidError) as refused:
        form_field_change(
            saved_metadata=_form(*saved), metadata=_form(*new), renames=renames
        )

    assert (refused.value.context or {})["problem"] == problem


def test_two_fields_may_swap_names():
    change = form_field_change(
        saved_metadata=_form("a", "b"),
        metadata=_form("b", "a"),
        renames={"a": "b", "b": "a"},
    )
    step = _step(1, question="{{ a }} {{ flow_input.b }}")

    structure = restructure_steps(_kept(step), prompts={}, form_fields=change)

    assert change.removed == frozenset()
    assert _question(structure.steps[0]) == "{{ b }} {{ flow_input.a }}"
