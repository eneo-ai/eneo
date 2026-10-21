from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_step_structure import (
    PlacedStep,
    StepReadLostItsProducerError,
    restructure_steps,
)
from eneo.flows.domain.flow import FlowStep


def _step(order: int, *, question: str | None = None) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=order,
        user_description=f"Step {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_type="text",
        input_bindings={"question": question} if question is not None else None,
        output_mode="pass_through",
        output_type="text",
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
    assert structure.renumbered_prompts == {
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
    assert structure.renumbered_prompts == {}


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

    with pytest.raises(StepReadLostItsProducerError):
        restructure_steps(_kept(second, first), prompts={})


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
    assert structure.renumbered_prompts == {}


def test_a_dangling_read_that_would_name_a_step_is_refused():
    first, second = _step(1), _step(2, question="{{step_5.output}}")
    new_steps = [PlacedStep(step=_step(10 + index)) for index in range(4)]

    # Kept where it was it still names no step.
    restructure_steps([*_kept(first, second), *new_steps], prompts={})

    with pytest.raises(StepReadLostItsProducerError):
        restructure_steps(
            [
                PlacedStep(step=first, saved=first),
                *new_steps,
                PlacedStep(step=second, saved=second),
            ],
            prompts={},
        )
