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

from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_edit_effect import (
    ReadEffect,
    ReadKey,
    edit_effect,
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
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_MESSAGE_LENGTH,
)
from eneo.flows.ai_builder.ai_builder_step_reads import ReadChannel, ReadSite
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
)

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
    final = compile_edit_proposal(
        OrderedEditProposal(plan_rationale="Edit.", steps=list(steps), **proposal),
        saved_steps,
        base_flow_revision=1,
        flow_name=raw["name"],
        flow_description=raw["description"],
        current_metadata_json=raw["metadata_json"],
        assistant_snapshots=snapshots,
    ).spec
    return saved, final


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
    "the run text": {"question": "{{ indata_text }}"},
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


def test_a_null_list_on_an_exact_input_is_refused_with_its_lists() -> None:
    message = _refusal(
        _writer(EXACT_WRITER),
        *_keep(1, 2),
        _modify(S3, uses_previous_fields=[BESLUT_READ, MOTIVERING_READ]),
    )

    assert "uses_form_fields is null" in message
    assert KEEP_AS_SAVED in message
    assert '- uses_form_fields: "namn"' in message
    assert f"- uses_previous_fields: {json.dumps(BESLUT_READ)}" in message


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
    assert f"- uses_previous_fields: {json.dumps(BESLUT_READ)}" in message


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
