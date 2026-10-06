"""An edit that changes a step's input never drops a saved read nobody named.

A modify that changes `input_source` or `input_type`, or says either read list,
rebuilds the step's input from the two lists; a list left null compiled as
empty. Now a rebuild is refused while it would drop a saved read, with a repair
that can pass. The compiler judges what the lists can restate: a saved input is
restatable only when its lists compile back to it exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    EditCompilationResult,
    _settle_run_form,
    compile_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_form_field_usage import find_unused_form_fields
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_step_input_bindings,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousFieldRef
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    FlowInputFieldIntent,
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_MESSAGE_LENGTH,
)
from eneo.flows.ai_builder.ai_builder_step_reads import (
    ReadChannel,
    ReadSite,
    step_template_sites,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationError
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    StepSpec,
)
from eneo.flows.flow_variable_definitions import FlowRunInput
from tests.unittests.flows.ai_builder.edit_effect_test_support import (
    ReadEffect,
    ReadKey,
    edit_effect,
)


def _errors(spec: FlowDraftSpecCore) -> list[SpecValidationError]:
    return [
        error
        for error in validate_spec(spec).errors
        if error.code == FlowGraphIssueCode.FLOW_INPUT_ALIAS_NOT_RECEIVED.value
    ]


SEEDS = Path(__file__).resolve().parents[4] / "scripts/fixtures/ai_builder_battle"
S1, S2, S3, S4 = (f"existing_step_{order}" for order in range(1, 5))
KEEP_AS_SAVED = "leave input_source, input_type and both lists null"


def _keep_steps(count: int) -> str:
    return (
        f"keep every step it reads before it ({count} of them this edit removes or "
        f"moves after it) and {KEEP_AS_SAVED}"
    )


def _seed(name: str) -> dict[str, Any]:
    return json.loads((SEEDS / name).read_text())


def _flow(*steps: dict[str, Any], form: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "name": "Flöde",
        "description": "Ett flöde.",
        "metadata_json": {
            "form_schema": {
                "fields": [
                    {"name": name, "type": "text", "label": name} for name in form
                ]
            }
        },
        "steps": [
            {
                "instructions": "Gör uppgiften.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "text",
                **step,
            }
            for step in steps
        ],
    }


def _edit(
    raw: dict[str, Any], *steps: ModifyExistingStep, **proposal: Any
) -> tuple[FlowDraftSpecCore, FlowDraftSpecCore]:
    """The flow as the edit compiler reads it, and the spec it compiles."""

    saved, result = _compile(raw, *steps, **proposal)
    return saved, result.spec


def _compile(
    raw: dict[str, Any],
    *steps: ModifyExistingStep,
    saved_step_revision: bool = False,
    template_placeholders: tuple[str, ...] | None = None,
    revision_form_fields: list[FormFieldSpec] | None = None,
    **proposal: Any,
) -> tuple[FlowDraftSpecCore, EditCompilationResult]:
    """The flow as the edit compiler reads it, and the whole compilation."""

    saved_steps = [
        FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=order,
            user_description=step["name"],
            input_source=step["input_source"],
            input_type=step["input_type"],
            output_mode=step["output_mode"],
            output_type=step["output_type"],
            input_bindings=step.get("input_bindings"),
            output_contract=step.get("output_contract"),
            output_config=step.get("output_config"),
        )
        for order, step in enumerate(raw["steps"], 1)
    ]
    snapshots = {
        flow_step.assistant_id: AssistantAuthoringSnapshot(
            instructions=step["instructions"]
        )
        for flow_step, step in zip(saved_steps, raw["steps"], strict=True)
    }
    saved = current_flow_authoring_spec(
        current_steps=saved_steps,
        flow_name=raw["name"],
        flow_description=raw["description"],
        assistant_snapshots=snapshots,
        form_fields=extract_form_fields_from_metadata(raw["metadata_json"]),
    )
    result = compile_edit_proposal(
        OrderedEditProposal(plan_rationale="Edit.", steps=list(steps), **proposal),
        saved_steps,
        base_flow_revision=1,
        flow_name=raw["name"],
        flow_description=raw["description"],
        current_metadata_json=raw["metadata_json"],
        assistant_snapshots=snapshots,
        revision_spec=(
            saved.model_copy(update={"form_fields": revision_form_fields})
            if saved_step_revision and revision_form_fields is not None
            else saved
            if saved_step_revision
            else None
        ),
        selected_template_count=None if template_placeholders is None else 1,
        selected_template_placeholders=template_placeholders,
    )
    return saved, result


def _refusal(raw: dict[str, Any], *steps: ModifyExistingStep, **proposal: Any) -> str:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _edit(raw, *steps, **proposal)
    assert exc_info.value.code is AIBuilderErrorCode.INVALID_PLAN_STEP_REF
    return str(exc_info.value)


def _keep(*orders: int) -> list[ModifyExistingStep]:
    return [ModifyExistingStep(existing_step_ref=f"existing_step_{o}") for o in orders]


def _modify(ref: str, **patch: Any) -> ModifyExistingStep:
    return ModifyExistingStep.model_validate({"existing_step_ref": ref, **patch})


def _removed_reads(saved: FlowDraftSpecCore, final: FlowDraftSpecCore) -> set[ReadKey]:
    return {
        effect.read
        for effect in edit_effect(saved, final).effects
        if isinstance(effect, ReadEffect) and effect.change == "removed"
    }


RESTATED_INPUT = {"input_source": "previous_step", "input_type": "text"}
EXACT_ONLY = "cannot restate exactly"

DECISION = {
    "name": "Läs ärendet",
    "input_source": "flow_input",
    "output_type": "json",
    "output_contract": {
        "type": "object",
        "properties": {
            "beslut": {"type": "string"},
            "motivering": {"type": "string"},
            "poster": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"titel": {"type": "string"}},
                },
            },
        },
    },
}
SUMMARY = {
    "name": "Sammanfatta",
    "output_type": "json",
    "output_contract": {
        "type": "object",
        "properties": {"sammanfattning": {"type": "string"}},
    },
}
BESLUT = {
    "step_ref": "step_1",
    "output": "structured",
    "field_path": "beslut",
    "label": "Beslut",
}
SAMMANFATTNING = {
    "step_ref": "step_2",
    "output": "structured",
    "field_path": "sammanfattning",
    "label": "Sammanfattning",
}


def _writer(bindings: dict[str, Any], **form: Any) -> dict[str, Any]:
    return _flow(
        DECISION,
        SUMMARY,
        {"name": "Skriv beslut", "input_bindings": bindings},
        form=form.get("form", ("namn", "tags")),
    )


# A restated input that changes nothing is no rebuild.


def test_int02_a_restated_input_keeps_the_saved_input() -> None:
    # me_int02: only a review checkpoint was asked for; steps 3 and 4 restated
    # their saved input_source and input_type.
    saved, final = _edit(
        _seed("edit_seed_int02.json"),
        *_keep(1),
        _modify(S2, review_mode="view"),
        _modify(S3, **RESTATED_INPUT),
        _modify(S4, **RESTATED_INPUT),
    )

    effects = edit_effect(saved, final).effects
    assert not any(isinstance(effect, ReadEffect) for effect in effects)
    assert not any(
        getattr(effect, "field", None) == "input_bindings" for effect in effects
    )


def test_int02_leaving_the_input_null_keeps_it_as_saved() -> None:
    saved, final = _edit(
        _seed("edit_seed_int02.json"),
        *_keep(1, 2, 3),
        _modify(S4, assistant_spec={"instructions": "Skriv beslutet kort."}),
    )

    assert not any(
        isinstance(effect, ReadEffect) for effect in edit_effect(saved, final).effects
    )


# An input the lists cannot restate exactly is kept only as saved.

UNRESTATABLE_INPUTS = {
    "literal text": {"question": "Skriv beslutet kort och sakligt."},
    "hand-written labels": {"question": "Sökande: {{ flow_input.namn }}"},
    "an indexed form read": {"question": "namn: {{ flow_input.tags.0 }}"},
    "the whole form": {"question": "{{ flow_input }}"},
    "a flow alias": {"question": "{{ flow.input.namn }}"},
    "an upload read": {"question": "{{ step_input.text }}"},
    "a step template": {"question": "Utkast: {{ step_2.output.text }}"},
    "a whole output": {
        "source_refs": [{"step_ref": "step_2", "output": "text", "label": "Utkast"}]
    },
    "an item template": {
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "poster",
                "label": "Poster",
                "item_template": "{titel}",
            }
        ]
    },
    "no label": {
        "source_refs": [
            {"step_ref": "step_1", "output": "structured", "field_path": "beslut"}
        ]
    },
}


@pytest.mark.parametrize("kind", list(UNRESTATABLE_INPUTS))
def test_an_input_the_lists_cannot_restate_is_kept_only_as_saved(kind: str) -> None:
    message = _refusal(
        _writer(UNRESTATABLE_INPUTS[kind]),
        *_keep(1, 2),
        _modify(S3, uses_form_fields=["namn"], uses_previous_fields=[BESLUT_READ]),
    )

    assert EXACT_ONLY in message
    assert KEEP_AS_SAVED in message
    assert "complete" not in message


def test_liv01_a_hand_written_question_is_kept_only_as_saved() -> None:
    message = _refusal(
        _seed("edit_seed_liv01.json"),
        *_keep(1, 2),
        _modify(
            S3,
            uses_previous_fields=[
                {
                    "from_step": 2,
                    "field_path": "kontroller_per_ar",
                    "label": "Kontroller per år",
                }
            ],
        ),
    )

    assert 'Step 3 "Skriv registreringsbeslut"' in message
    assert EXACT_ONLY in message


def test_an_unlabeled_field_read_restated_gains_a_label() -> None:
    # Why an unlabeled saved read does not restate: the compiler labels it.
    bindings = compile_step_input_bindings(
        run_input=FlowRunInput(),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[PreviousFieldRef(from_step=1, field_path="beslut")],
        uses_previous_outputs=[],
        prior_steps=_edit(_flow(DECISION, {"name": "Skriv"}), *_keep(1, 2))[1].steps[
            :1
        ],
    )

    assert bindings is not None
    assert bindings["source_refs"][0].get("label") is not None


# An input the lists restate exactly: a null list whose kind it reads.

EXACT_WRITER = {"question": "namn: {{ flow_input.namn }}", "source_refs": [BESLUT]}
BESLUT_READ = {"from_step": 1, "field_path": "beslut", "label": "Beslut"}
MOTIVERING_READ = {"from_step": 1, "field_path": "motivering", "label": "Motivering"}
BESLUT_COMMAND_READ = {
    "producer": {"kind": "saved", "existing_step_ref": S1},
    "field_path": "beslut",
    "label": "Beslut",
}


def test_a_null_list_on_an_exact_input_is_refused_with_its_lists() -> None:
    message = _refusal(
        _writer(EXACT_WRITER),
        *_keep(1, 2),
        _modify(S3, uses_previous_fields=[BESLUT_READ, MOTIVERING_READ]),
    )

    assert "uses_form_fields is null" in message
    assert KEEP_AS_SAVED in message
    assert '- uses_form_fields: "namn"' in message
    assert f"- uses_previous_fields: {json.dumps(BESLUT_COMMAND_READ)}" in message


def test_both_lists_complete_on_an_exact_input_add_only_the_new_read() -> None:
    saved, final = _edit(
        _writer(EXACT_WRITER),
        *_keep(1, 2),
        _modify(
            S3,
            uses_form_fields=["namn"],
            uses_previous_fields=[BESLUT_READ, MOTIVERING_READ],
        ),
    )

    assert _removed_reads(saved, final) == set()
    assert find_unused_form_fields(final) == ["tags"]


# A step whose producer the edit removes names its new reads.

REMOVED_SUMMARY = _writer({"source_refs": [SAMMANFATTNING]})


@pytest.mark.parametrize(
    "patch",
    [
        {"input_type": "json"},
        # With a JSON predecessor the compiler would read old step 1 anyway.
        {"uses_form_fields": [], "uses_previous_fields": []},
    ],
)
def test_a_step_whose_producer_is_removed_must_name_its_new_reads(
    patch: dict[str, Any],
) -> None:
    message = _refusal(
        REMOVED_SUMMARY,
        *_keep(1),
        _modify(S3, **patch),
        removed_existing_step_refs=frozenset({S2}),
    )

    assert '"Sammanfatta" is removed by this edit' in message
    assert "uses_form_fields and uses_previous_fields" in message
    # Leaving the input null alone would keep a read of the removed step.
    assert f"or {_keep_steps(1)}." in message


def test_a_named_replacement_read_names_its_producer() -> None:
    saved, final = _edit(
        REMOVED_SUMMARY,
        *_keep(1),
        _modify(S3, uses_form_fields=[], uses_previous_fields=[BESLUT_READ]),
        removed_existing_step_refs=frozenset({S2}),
    )

    assert (
        ReadEffect(
            S3,
            "added",
            ReadKey(
                S1, ReadChannel.STRUCTURED, ("beslut",), ReadSite.SOURCE_REF, "Beslut"
            ),
        )
        in edit_effect(saved, final).effects
    )


def test_a_read_of_a_removed_step_offers_null_only_with_that_step_kept() -> None:
    # Leaving the input null keeps the read of the removed summary, which the
    # alias guard refuses unless the summary stays.
    message = _refusal(
        _writer({"source_refs": [SAMMANFATTNING, BESLUT]}),
        *_keep(1),
        _modify(S3, uses_form_fields=["namn"]),
        removed_existing_step_refs=frozenset({S2}),
    )

    assert f"To keep them, give both lists complete, or {_keep_steps(1)}." in message
    assert f"or {KEEP_AS_SAVED}" not in message
    assert f"- uses_previous_fields: {json.dumps(BESLUT_COMMAND_READ)}" in message


# The list contract: a list names explicit reads; the source read stays.


def test_authored_form_reads_on_an_implicit_step_keep_its_predecessor_read() -> None:
    _, final = _edit(
        _flow(DECISION, {"name": "Skriv"}, form=("namn",)),
        *_keep(1),
        _modify(S2, uses_form_fields=["namn"]),
    )

    assert final.steps[1].input_bindings == {
        "question": "namn: {{ flow_input.namn }}",
        "source_refs": [
            {"step_ref": final.steps[0].plan_step_ref, "output": "structured"}
        ],
    }


def test_an_inexact_input_reading_a_removed_step_can_only_keep_that_step() -> None:
    # Naming new reads would still drop the hand-written question, and leaving
    # the input null keeps a read of the removed step: only keeping it passes.
    message = _refusal(
        _writer({"question": "Sammanfattning: {{ step_2.output.structured }}"}),
        *_keep(1),
        _modify(S3, input_type="json"),
        removed_existing_step_refs=frozenset({S2}),
    )

    assert f"To keep it, {_keep_steps(1)}." in message
    assert '"Sammanfatta" is removed by this edit' in message
    assert "Name what" not in message


def test_a_long_refusal_shows_its_first_reads_whole_within_the_cap() -> None:
    names = tuple(f"falt_{index:02}" for index in range(40))
    question = "\n".join(f"{name}: {{{{ flow_input.{name} }}}}" for name in names)
    message = _refusal(
        _flow(
            DECISION,
            SUMMARY,
            {
                "name": "Skriv beslut",
                "input_bindings": {"question": question, "source_refs": [BESLUT]},
            },
            form=names,
        ),
        *_keep(1, 2),
        _modify(S3, uses_previous_fields=[BESLUT_READ, MOTIVERING_READ]),
    )

    shown = [line for line in message.splitlines() if line.startswith("- ")]
    assert len(message) <= MAX_DIAGNOSTIC_MESSAGE_LENGTH
    assert shown[:2] == [
        '- uses_form_fields: "falt_00"',
        '- uses_form_fields: "falt_01"',
    ]
    assert message.endswith(f"... and {41 - len(shown)} more.")


def test_a_long_refusal_names_the_removed_step_first() -> None:
    names = tuple(f"falt_{index:02}" for index in range(40))
    question = "\n".join(f"{name}: {{{{ flow_input.{name} }}}}" for name in names)
    message = _refusal(
        _flow(
            DECISION,
            SUMMARY,
            {
                "name": "Skriv beslut",
                "input_bindings": {
                    "question": question,
                    "source_refs": [BESLUT, SAMMANFATTNING],
                },
            },
            form=names,
        ),
        *_keep(1),
        _modify(S3, uses_previous_fields=[BESLUT_READ]),
        removed_existing_step_refs=frozenset({S2}),
    )

    shown = [line for line in message.splitlines() if line.startswith("- ")]
    assert shown[0] == (
        '- saved step "Sammanfatta" is removed by this edit; read 1 time, e.g. '
        "{{ step_2.output.structured.sammanfattning }}"
    )
    assert len(message) <= MAX_DIAGNOSTIC_MESSAGE_LENGTH


def test_a_refusal_names_every_removed_step_it_reads_once() -> None:
    fields = [f"falt_{index}" for index in range(8)]
    read_everything = {
        **DECISION,
        "output_contract": {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
        },
    }
    message = _refusal(
        _flow(
            read_everything,
            SUMMARY,
            {
                "name": "Skriv beslut",
                "input_bindings": {
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": field,
                            "label": field,
                        }
                        for field in fields
                    ]
                    + [SAMMANFATTNING]
                },
            },
        ),
        _modify(S3, input_type="json"),
        removed_existing_step_refs=frozenset({S1, S2}),
    )

    shown = [line for line in message.splitlines() if line.startswith("- ")]
    assert shown[:2] == [
        '- saved step "Läs ärendet" is removed by this edit; read 8 times, e.g. '
        "{{ step_1.output.structured.falt_0 }}",
        '- saved step "Sammanfatta" is removed by this edit; read 1 time, e.g. '
        "{{ step_2.output.structured.sammanfattning }}",
    ]


def _many_producers(count: int, *, name: str = "Sammanfatta") -> dict[str, Any]:
    """A writer reading one field of each of `count` summary steps."""

    orders = range(2, count + 2)
    return _flow(
        DECISION,
        *(
            {**SUMMARY, "name": f"{name} {order}", "input_source": "previous_step"}
            for order in orders
        ),
        {
            "name": "Skriv beslut",
            "input_bindings": {
                "source_refs": [
                    {
                        **SAMMANFATTNING,
                        "step_ref": f"step_{order}",
                        "label": f"S{order}",
                    }
                    for order in orders
                ]
            },
        },
    )


@pytest.mark.parametrize(
    ("count", "name"),
    [
        (10, "Sammanfatta"),  # More steps than entries.
        (8, "Sammanfatta " + "mycket " * 11),  # Long names: the character cap.
    ],
)
def test_the_keep_repair_names_no_step_and_compiles(count: int, name: str) -> None:
    raw = _many_producers(count, name=name)
    writer = f"existing_step_{count + 2}"
    removed = frozenset(f"existing_step_{order}" for order in range(2, count + 2))

    message = _refusal(
        raw,
        *_keep(1),
        _modify(writer, input_type="json"),
        removed_existing_step_refs=removed,
    )

    shown = [line for line in message.splitlines() if line.startswith("- ")]
    assert len(shown) < count
    assert len(message) <= MAX_DIAGNOSTIC_MESSAGE_LENGTH
    assert f"or {_keep_steps(count)}." in message
    # The repair as stated: every step kept, the input left null.
    saved, final = _edit(raw, *_keep(*range(1, count + 2)), _modify(writer))
    assert final.steps[-1].input_bindings is not None
    assert _removed_reads(saved, final) == set()


# The run text is read only where the run form collects it. A form flow has no
# text box, so its main text is a field or it is not read: an edit that would
# leave a read of it without a place is refused, never rewritten.

FORM_RUN_LEGACY_READ = {"question": "{{ indata_text }}\n\nnamn: {{ flow_input.namn }}"}
FORM_RUN_READ = {"question": "namn: {{ flow_input.namn }}"}
MAIN_TEXT_FIELD = FlowInputFieldIntent(
    name="input", label="Underlag", type="text", required=True
)
NAMN_FIELD = FlowInputFieldIntent(name="namn", label="Namn", type="text")


def test_a_form_run_step_without_a_run_text_read_rebuilds_unchanged() -> None:
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_READ}, form=("namn",))

    _, final = _edit(raw, _modify(S1, uses_form_fields=["namn"]))

    assert final.steps[0].input_bindings == FORM_RUN_READ
    assert not _errors(final)


def test_a_text_run_step_keeps_reading_the_run_text_when_rebuilt() -> None:
    raw = _flow({**DECISION, "input_bindings": {"question": "{{ indata_text }}"}})

    _, final = _edit(raw, _modify(S1, uses_form_fields=[]))

    assert final.steps[0].input_bindings == {"question": "{{ indata_text }}"}
    assert not _errors(final)


def test_a_rebuild_of_a_form_run_step_does_not_drop_its_main_text_read() -> None:
    # A flow saved with the read and form fields (the run has no text box).
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_LEGACY_READ}, form=("namn",))

    message = _refusal(raw, _modify(S1, uses_form_fields=["namn"]))

    assert (
        'Step 1 "Läs ärendet" (existing_step_1) reads the flow\'s main text' in message
    )
    assert "main text cannot be collected beside form fields" in message
    assert "`input`" in message


def test_the_main_text_declared_as_a_field_replaces_the_run_text_read() -> None:
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_LEGACY_READ}, form=("namn",))

    _, final = _edit(
        raw,
        _modify(S1, uses_form_fields=["namn", "input"]),
        form_fields=[NAMN_FIELD, MAIN_TEXT_FIELD],
    )

    assert final.steps[0].input_bindings == {
        "question": "namn: {{ flow_input.namn }}\ninput: {{ flow_input.input }}"
    }
    assert [(field.name, field.required) for field in final.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]
    assert not _errors(final)


def test_a_form_field_added_to_a_text_flow_that_reads_its_text_is_refused() -> None:
    raw = _flow(
        {**DECISION, "input_bindings": {"question": "{{ indata_text }}"}},
        {"name": "Sammanfatta", "input_bindings": {"question": "x"}},
    )

    _, kept = _edit(raw, *_keep(1, 2), form_fields=[NAMN_FIELD])

    errors = _errors(kept)
    assert [error.step_ref for error in errors] == ["step_a"]
    assert 'Step 1 "Läs ärendet" (existing_step_1)' in errors[0].message
    assert "The step to modify is existing_step_1." in errors[0].message
    assert kept.steps[0].input_bindings == {"question": "{{ indata_text }}"}


def test_a_main_text_field_beside_others_is_kept_and_required_in_an_edit() -> None:
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_READ}, form=("namn",))

    _, final = _edit(
        raw,
        _modify(S1, uses_form_fields=["namn", "input"]),
        form_fields=[
            NAMN_FIELD,
            FlowInputFieldIntent(name="input", label="Underlag", type="text"),
        ],
    )

    assert [(field.name, field.required) for field in final.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]
    assert "input: {{ flow_input.input }}" in final.steps[0].input_bindings["question"]


def test_a_reserved_name_is_dropped_not_kept_as_the_main_text_field_in_an_edit() -> (
    None
):
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_READ}, form=("namn",))

    _, final = _edit(
        raw,
        _modify(S1, uses_form_fields=["namn", "input"]),
        form_fields=[
            NAMN_FIELD,
            FlowInputFieldIntent(name="text", label="Text", type="text"),
            FlowInputFieldIntent(name="input", label="Underlag", type="text"),
        ],
    )

    # `text` is a runtime payload key the form schema rejects: it cannot carry
    # the main text. `input` can, and stays, required.
    assert [(f.name, f.required) for f in final.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]


def test_the_edit_refusal_names_a_main_text_name_no_field_holds() -> None:
    raw = _flow(
        {**DECISION, "input_bindings": {"question": "{{ indata_text }}"}},
        {"name": "Sammanfatta", "input_bindings": {"question": "x"}},
    )
    taken = FlowInputFieldIntent(
        name="input", label="Prioritet", type="select", options=["Låg", "Hög"]
    )

    _, kept = _edit(raw, *_keep(1, 2), form_fields=[taken])

    message = _errors(kept)[0].message
    # `input` is a select the edit keeps: the repair names the next free name.
    assert "named `indata_text`" in message
    assert "named `input`" not in message


def test_exactly_one_main_text_field_is_elected_in_an_edit_and_the_other_is_unchanged() -> (
    None
):
    raw = _flow({**DECISION, "input_bindings": FORM_RUN_READ}, form=("namn",))

    _, final = _edit(
        raw,
        _modify(S1, uses_form_fields=["namn", "indata_text", "input"]),
        form_fields=[
            NAMN_FIELD,
            FlowInputFieldIntent(name="indata_text", label="Anteckning", type="text"),
            FlowInputFieldIntent(name="input", label="Underlag", type="text"),
        ],
    )

    # `input` is elected first in the fixed order, so only it is required;
    # `indata_text` keeps its contract and its read.
    assert [(f.name, f.label, f.required) for f in final.form_fields or ()] == [
        ("namn", "Namn", False),
        ("indata_text", "Anteckning", False),
        ("input", "Underlag", True),
    ]
    question = final.steps[0].input_bindings["question"]
    assert "indata_text: {{ flow_input.indata_text }}" in question
    assert "input: {{ flow_input.input }}" in question


def _typed_form(raw: dict[str, Any], *fields: dict[str, Any]) -> dict[str, Any]:
    raw["metadata_json"]["form_schema"]["fields"] = list(fields)
    return raw


def _form_diff(result: EditCompilationResult) -> list[tuple[str, str]]:
    return [
        (change.kind, change.field_name)
        for change in result.authored_approval.diff.form_changes
    ]


PRIORITY_SELECT = {
    "name": "input",
    "type": "select",
    "label": "Prioritet",
    "options": ["Låg", "Hög"],
}
NAMN_TEXT = {"name": "namn", "type": "text", "label": "Namn"}
NOTE_TEXT = {"name": "indata_text", "type": "text", "label": "Anteckning"}
OPTIONAL_INPUT = {"name": "input", "type": "text", "label": "Underlag"}


def test_a_rebuild_reads_the_text_field_elected_beside_a_select_named_input() -> None:
    # `input` is a select here, so it cannot carry the main text: the election
    # is by type, and `indata_text` is the field the rebuild has to keep.
    raw = _typed_form(
        _flow({**DECISION, "input_bindings": FORM_RUN_LEGACY_READ}),
        NAMN_TEXT,
        PRIORITY_SELECT,
        NOTE_TEXT,
    )

    _, final = _edit(raw, _modify(S1, uses_form_fields=["namn", "indata_text"]))

    assert final.steps[0].input_bindings == {
        "question": "namn: {{ flow_input.namn }}\n"
        "indata_text: {{ flow_input.indata_text }}"
    }
    assert [(f.name, f.required) for f in final.form_fields or ()] == [
        ("namn", False),
        ("input", False),
        ("indata_text", True),
    ]


def test_a_rebuild_that_skips_the_elected_text_field_names_it_not_the_select() -> None:
    raw = _typed_form(
        _flow({**DECISION, "input_bindings": FORM_RUN_LEGACY_READ}),
        NAMN_TEXT,
        PRIORITY_SELECT,
        NOTE_TEXT,
    )

    message = _refusal(raw, _modify(S1, uses_form_fields=["namn", "input"]))

    assert "reads the flow's main text" in message
    assert "`indata_text`" in message


def test_a_step_only_edit_that_binds_an_optional_main_text_field_requires_it() -> None:
    raw = _typed_form(
        _flow(
            {**DECISION, "input_bindings": FORM_RUN_READ},
            {"name": "Sammanfatta"},
        ),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    _, result = _compile(
        raw,
        *_keep(1),
        _modify(S2, uses_form_fields=["input"], input_source="flow_input"),
    )

    # The edit omits form_fields: the saved optional `input` is made required,
    # as part of the edit, and the form diff says so.
    fields = result.spec.form_fields or []
    assert [(f.name, f.required) for f in fields] == [("namn", False), ("input", True)]
    assert _form_diff(result) == [("modified", "input")]
    assert "input: {{ flow_input.input }}" in (
        result.spec.steps[1].input_bindings or {}
    ).get("question", "")


def test_a_step_only_edit_keeps_a_saved_read_of_the_main_text_field_as_it_was() -> None:
    raw = _typed_form(
        _flow(
            {
                **DECISION,
                "input_bindings": {
                    "question": "namn: {{ flow_input.namn }}\n"
                    "input: {{ flow_input.input }}"
                },
            },
        ),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    _, result = _compile(raw, _modify(S1, uses_form_fields=["namn", "input"]))

    # The flow already read the field; a restated read binds nothing new.
    assert [(f.name, f.required) for f in result.spec.form_fields or ()] == [
        ("namn", False),
        ("input", False),
    ]
    assert _form_diff(result) == []


def test_a_step_only_edit_that_leaves_the_main_text_field_unread_changes_no_field() -> (
    None
):
    raw = _typed_form(
        _flow({**DECISION, "input_bindings": FORM_RUN_READ}),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    _, result = _compile(raw, _modify(S1, name="Läs ärendet noga"))

    assert _form_diff(result) == []


def test_a_saved_step_edit_cannot_make_the_bound_main_text_field_required() -> None:
    raw = _typed_form(
        _flow(
            {**DECISION, "input_bindings": FORM_RUN_READ},
            {"name": "Sammanfatta"},
        ),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _compile(
            raw,
            *_keep(1),
            _modify(S2, uses_form_fields=["input"], input_source="flow_input"),
            saved_step_revision=True,
        )

    message = str(exc_info.value)
    assert "single-step edit cannot change the run form" in message
    assert "make `input` required" in message
    assert "whole-flow edit" in message


MAIN_TEXT_READ = "Läs {{ flow_input.input }} noga."


def test_an_instructions_only_edit_that_binds_the_main_text_field_requires_it() -> None:
    raw = _typed_form(
        _flow(
            {**DECISION, "input_bindings": FORM_RUN_READ},
            {"name": "Sammanfatta"},
        ),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    _, result = _compile(
        raw, *_keep(1), _modify(S2, assistant_spec={"instructions": MAIN_TEXT_READ})
    )

    assert [(f.name, f.required) for f in result.spec.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]
    assert _form_diff(result) == [("modified", "input")]
    assert result.spec.steps[1].assistant_spec.instructions == MAIN_TEXT_READ


def test_a_saved_step_instructions_edit_binding_the_main_text_field_is_refused() -> (
    None
):
    raw = _typed_form(
        _flow(
            {**DECISION, "input_bindings": FORM_RUN_READ},
            {"name": "Sammanfatta"},
        ),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _compile(
            raw,
            *_keep(1),
            _modify(S2, assistant_spec={"instructions": MAIN_TEXT_READ}),
            saved_step_revision=True,
        )

    message = str(exc_info.value)
    assert "single-step edit cannot change the run form" in message
    assert "make `input` required" in message


# One carrier per template site the Builder's owner enumerates, so a site the
# owner gains and this table lacks fails the coverage test below.
SITE_CARRIERS: dict[ReadSite, dict[str, Any]] = {
    ReadSite.INSTRUCTIONS: {
        "assistant_spec": AssistantSpec(instructions=MAIN_TEXT_READ)
    },
    ReadSite.QUESTION: {"input_bindings": {"question": MAIN_TEXT_READ}},
    # Only a template fill's bindings are interpolated; other configuration is text.
    ReadSite.OUTPUT_CONFIG: {
        "output_mode": "template_fill",
        "output_type": "docx",
        "output_config": {"bindings": {"filename": MAIN_TEXT_READ}},
    },
}


def _step(**carriers: Any) -> StepSpec:
    return StepSpec.model_validate(
        {
            "plan_step_ref": "step_a",
            "existing_step_ref": S1,
            "name": "Läs ärendet",
            "assistant_spec": AssistantSpec(instructions="Gör uppgiften."),
            "input_source": InputSource.PREVIOUS_STEP,
            **carriers,
        }
    )


def _form_spec(step: StepSpec) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flöde",
        steps=[step],
        form_fields=[
            FormFieldSpec(name="namn", type="text", label="Namn"),
            FormFieldSpec(name="input", type="text", label="Underlag"),
        ],
    )


def test_the_site_table_covers_every_template_site_the_owner_enumerates() -> None:
    everything = _step(
        **{
            key: value
            for carrier in SITE_CARRIERS.values()
            for key, value in carrier.items()
        }
    )

    assert {site for site, _ in step_template_sites(everything)} == set(SITE_CARRIERS)


@pytest.mark.parametrize("site", list(SITE_CARRIERS), ids=lambda site: site.value)
def test_a_main_text_read_at_any_site_makes_the_field_required(site: ReadSite) -> None:
    saved, compiled = _form_spec(_step()), _form_spec(_step(**SITE_CARRIERS[site]))

    required = _settle_run_form(
        compiled, baseline=saved, main_text_field="input", scoped=False
    )
    assert [(f.name, f.required) for f in required.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]
    with pytest.raises(AIBuilderBadRequestException, match="whole-flow edit"):
        _settle_run_form(
            compiled,
            baseline=saved,
            main_text_field="input",
            scoped=True,
        )


@pytest.mark.parametrize("site", list(SITE_CARRIERS), ids=lambda site: site.value)
def test_a_main_text_read_the_saved_step_already_has_changes_no_field(
    site: ReadSite,
) -> None:
    both = _form_spec(_step(**SITE_CARRIERS[site]))

    unchanged = _settle_run_form(
        both, baseline=both, main_text_field="input", scoped=True
    )

    assert unchanged is both


def test_a_step_newly_reading_the_whole_run_input_reads_the_main_text_field() -> None:
    saved = _form_spec(_step())
    compiled = _form_spec(_step(input_bindings={"question": "{{ flow_input }}"}))

    required = _settle_run_form(
        compiled, baseline=saved, main_text_field="input", scoped=False
    )

    assert [(f.name, f.required) for f in required.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]


TEMPLATE_STEP = {
    "name": "Fyll mall",
    "output_mode": "template_fill",
    "output_type": "docx",
    "output_config": {"bindings": {"namn": "{{ flow_input.namn }}"}},
}


def _template_flow() -> dict[str, Any]:
    return _typed_form(
        _flow({**DECISION, "input_bindings": FORM_RUN_READ}, TEMPLATE_STEP),
        NAMN_TEXT,
        OPTIONAL_INPUT,
    )


def test_a_template_mapping_that_reads_the_main_text_field_requires_it() -> None:
    # The edit says nothing about the field; the selected template's mapping
    # is what reads `input`, added after the proposal is compiled.
    _, result = _compile(
        _template_flow(), *_keep(1, 2), template_placeholders=("namn", "input")
    )

    mapping = result.spec.steps[1].output_config or {}
    assert mapping["bindings"]["input"] == "{{ flow_input.input }}"
    assert [(f.name, f.required) for f in result.spec.form_fields or ()] == [
        ("namn", False),
        ("input", True),
    ]
    assert _form_diff(result) == [("modified", "input")]


def test_a_template_that_reads_no_main_text_field_changes_no_field() -> None:
    _, result = _compile(
        _template_flow(), *_keep(1, 2), template_placeholders=("namn",)
    )

    assert _form_diff(result) == []


def test_a_saved_step_edit_whose_template_mapping_reads_the_main_text_is_refused() -> (
    None
):
    # A selected-step edit of the template step attaches the template too: the
    # step is authored, so its new mapping is kept, and it cannot make the
    # optional field required.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _compile(
            _template_flow(),
            *_keep(1),
            _modify(S2, name="Fyll mallen"),
            saved_step_revision=True,
            template_placeholders=("namn", "input"),
        )

    message = str(exc_info.value)
    assert "single-step edit cannot change the run form" in message
    assert "make `input` required" in message


def test_a_saved_step_edit_of_another_step_ignores_the_mapping_it_restores() -> None:
    # The template step is protected: the attachment's new mapping is reverted
    # with it, so this edit reads nothing new and refuses nothing.
    _, result = _compile(
        _template_flow(),
        _modify(S1, name="Läs ärendet noga"),
        *_keep(2),
        saved_step_revision=True,
        template_placeholders=("namn", "input"),
    )

    assert _form_diff(result) == []
    assert result.spec.steps[1].output_config == TEMPLATE_STEP["output_config"]


EXTRA_PLACEHOLDERS = ("namn", "flow_input.extra")


def test_a_saved_step_template_edit_that_adds_a_run_field_is_refused() -> None:
    # The terminal step is authored, so the attachment's mapping is kept, and
    # a placeholder the flow does not collect adds a run-form field with it.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _compile(
            _template_flow(),
            *_keep(1),
            _modify(S2, name="Fyll mallen"),
            saved_step_revision=True,
            template_placeholders=EXTRA_PLACEHOLDERS,
        )

    message = str(exc_info.value)
    assert "single-step edit cannot change the run form" in message
    assert "add `extra`" in message
    assert "whole-flow edit" in message


def test_a_whole_flow_template_edit_may_add_the_run_field() -> None:
    _, result = _compile(
        _template_flow(), *_keep(1, 2), template_placeholders=EXTRA_PLACEHOLDERS
    )

    assert [f.name for f in result.spec.form_fields or ()] == ["namn", "input", "extra"]
    assert _form_diff(result) == [("added", "extra")]


def test_a_saved_step_edit_that_leaves_the_run_form_equal_passes() -> None:
    saved, result = _compile(
        _template_flow(),
        *_keep(1),
        _modify(S2, name="Fyll mallen"),
        saved_step_revision=True,
        template_placeholders=("namn",),
    )

    assert result.spec.form_fields == saved.form_fields
    assert _form_diff(result) == []
    assert result.spec.steps[1].name == "Fyll mallen"


_NAMN = FormFieldSpec(name="namn", type="text", label="Namn")
_INPUT = FormFieldSpec(name="input", type="text", label="Underlag")


@pytest.mark.parametrize(
    ("final", "described"),
    [
        ([_NAMN, _INPUT, FormFieldSpec(name="x", type="text", label="X")], "add `x`"),
        ([_NAMN], "remove `input`"),
        ([_NAMN, _INPUT.model_copy(update={"type": "date"})], "change `input`"),
        (
            [_NAMN, _INPUT.model_copy(update={"required": True})],
            "make `input` required",
        ),
        ([_INPUT, _NAMN], "reorder the fields"),
    ],
    ids=["added", "removed", "retyped", "required", "reordered"],
)
def test_a_saved_step_edit_is_refused_for_any_run_form_difference(
    final: list[FormFieldSpec], described: str
) -> None:
    baseline = _form_spec(_step())
    compiled = baseline.model_copy(update={"form_fields": final})

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _settle_run_form(
            compiled,
            baseline=baseline,
            main_text_field=None,
            scoped=True,
        )

    assert described in str(exc_info.value)
    assert (
        _settle_run_form(
            compiled, baseline=baseline, main_text_field=None, scoped=False
        )
        is compiled
    )


# A selected-step edit revises a spec that may carry run-form fields the saved
# metadata lacks (an earlier turn's state). Every stage reads that one baseline.
REVISION_FIELDS = [
    FormFieldSpec(name="namn", type="text", label="Namn"),
    FormFieldSpec(name="input", type="text", label="Underlag", required=True),
]


def _revision_only_flow() -> dict[str, Any]:
    return _typed_form(_flow({**DECISION, "input_bindings": FORM_RUN_READ}), NAMN_TEXT)


def test_a_saved_step_edit_keeps_a_read_of_a_field_only_the_revision_declares() -> None:
    _, result = _compile(
        _revision_only_flow(),
        _modify(S1, uses_form_fields=["namn", "input"]),
        saved_step_revision=True,
        revision_form_fields=REVISION_FIELDS,
    )

    question = (result.spec.steps[0].input_bindings or {}).get("question", "")
    assert "input: {{ flow_input.input }}" in question
    assert result.spec.form_fields == REVISION_FIELDS
    # The person's diff stays against the saved flow, which has no `input`.
    assert _form_diff(result) == [("added", "input")]


def test_preparation_compile_and_the_rule_read_one_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import eneo.flows.ai_builder.ai_builder_edit_compiler as compiler

    seen: dict[str, list[FormFieldSpec] | None] = {}

    def spy(name: str, original: Any, baseline: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seen[name] = baseline(kwargs)
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(
        compiler,
        "_prepare_ordered_edit_proposal",
        spy(
            "preparation",
            compiler._prepare_ordered_edit_proposal,
            lambda kwargs: kwargs["baseline_form_fields"],
        ),
    )
    monkeypatch.setattr(
        compiler,
        "compile_ordered_edit_proposal",
        spy(
            "compilation",
            compiler.compile_ordered_edit_proposal,
            lambda kwargs: kwargs["base_spec"].form_fields,
        ),
    )
    monkeypatch.setattr(
        compiler,
        "_settle_run_form",
        spy(
            "rule",
            compiler._settle_run_form,
            lambda kwargs: kwargs["baseline"].form_fields,
        ),
    )

    saved, _ = _compile(
        _revision_only_flow(),
        _modify(S1, uses_form_fields=["namn", "input"]),
        saved_step_revision=True,
        revision_form_fields=REVISION_FIELDS,
    )

    assert set(seen) == {"preparation", "compilation", "rule"}
    assert seen["preparation"] == seen["compilation"] == seen["rule"]
    assert seen["preparation"] == REVISION_FIELDS
    assert seen["preparation"] != saved.form_fields
