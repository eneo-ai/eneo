"""What an edit changed, read by step identity from the saved and the final spec.

The saved flows are the edit benchmark's seeds and the final specs come from
the product's edit compiler, so the effects are those of real edits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_edit_effect import (
    DocumentBodyWriterEffect,
    EditEffect,
    FieldEffect,
    FlowPropertyEffect,
    FormEffect,
    OrderEffect,
    ReadEffect,
    ReadKey,
    StructureEffect,
    edit_effect,
    order_matches_moves,
)
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep,
    AssistantSpecPatch,
    FlowInputFieldIntent,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_step_reads import ReadChannel, ReadSite
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec

SEEDS = Path(__file__).resolve().parents[4] / "scripts/fixtures/ai_builder_battle"
S1, S2, S3, S4 = (f"existing_step_{order}" for order in range(1, 5))
FIELD_READS_OF_S2_IN_A = [
    ("diarienummer", "Diarienummer"),
    ("bedomning", "Bedömning"),
    ("sista_datum", "Sista datum"),
]


def _edit(
    seed: str | dict[str, Any], *steps: ModifyExistingStep | AddStep, **proposal: Any
) -> tuple[FlowDraftSpecCore, FlowDraftSpecCore]:
    """The seed as the edit compiler reads it, and the spec it compiles."""

    raw = _seed(seed) if isinstance(seed, str) else seed
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
    # Instructions live on the step's assistant, read through its snapshot.
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


def _seed(name: str) -> dict[str, Any]:
    return json.loads((SEEDS / name).read_text())


def _keep(*orders: int) -> list[ModifyExistingStep]:
    return [ModifyExistingStep(existing_step_ref=f"existing_step_{o}") for o in orders]


def _read(
    consumer: str,
    change: str,
    producer: str | None,
    channel: ReadChannel,
    path: tuple[str, ...] = (),
    site: ReadSite = ReadSite.SOURCE_REF,
    label: str | None = None,
    item_template: str | None = None,
) -> ReadEffect:
    return ReadEffect(
        consumer,
        "added" if change == "+" else "removed",
        ReadKey(producer, channel, path, site, label, item_template),
    )


def _with_source_ref(
    spec: FlowDraftSpecCore, identity: str, index: int, **update: str
) -> FlowDraftSpecCore:
    """`spec` with one source ref of one step changed, validated as a step."""

    steps = []
    for step in spec.steps:
        if step.existing_step_ref == identity:
            bindings = dict(step.input_bindings or {})
            refs = [dict(ref) for ref in bindings["source_refs"]]
            refs[index].update(update)
            step = StepSpec.model_validate(
                {
                    **step.model_dump(),
                    "input_bindings": {**bindings, "source_refs": refs},
                }
            )
        steps.append(step)
    return spec.model_copy(update={"steps": steps})


def _s3_loses_its_saved_step_reads_in_a() -> set[ReadEffect]:
    return {
        _read(S3, "-", S1, ReadChannel.TEXT, label="Källfakta"),
        *(
            _read(S3, "-", S2, ReadChannel.STRUCTURED, (field,), label=label)
            for field, label in FIELD_READS_OF_S2_IN_A
        ),
    }


def test_an_edit_that_changes_nothing_has_no_effect() -> None:
    saved, final = _edit("edit_seed_a.json", *_keep(1, 2, 3))

    assert edit_effect(saved, final) == EditEffect(frozenset(), None)


def test_a_renamed_step_is_one_field_effect() -> None:
    saved, final = _edit(
        "edit_seed_a.json",
        *_keep(1),
        ModifyExistingStep(existing_step_ref=S2, name="Bedöm ansökan"),
        *_keep(3),
    )

    assert edit_effect(saved, final) == EditEffect(
        frozenset({FieldEffect(S2, "name")}), None
    )


@pytest.mark.parametrize(
    ("patch", "effect"),
    [
        ({"flow_name": "Bostadsanpassning"}, FlowPropertyEffect("flow_name")),
        ({"flow_description": "Kortare."}, FlowPropertyEffect("flow_description")),
    ],
)
def test_a_changed_flow_property_is_a_flow_property_effect(
    patch: dict[str, str], effect: FlowPropertyEffect
) -> None:
    saved, final = _edit("edit_seed_a.json", *_keep(1, 2, 3), **patch)

    assert edit_effect(saved, final) == EditEffect(frozenset({effect}), None)


def test_e10_a_producer_turned_text_drops_its_field_reads_for_one_text_read() -> None:
    saved, final = _edit(
        "edit_seed_a.json",
        *_keep(1),
        ModifyExistingStep(existing_step_ref=S2, output_type="text", output_fields=[]),
        ModifyExistingStep(
            existing_step_ref=S3,
            input_source="previous_step",
            input_type="text",
            uses_form_fields=["sokande", "sokt_belopp"],
        ),
    )

    # Today's wire cannot keep the source facts: their loss is reported.
    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FieldEffect(S2, "output_type"),
                FieldEffect(S2, "output_contract"),
                FieldEffect(S3, "input_bindings"),
                *_s3_loses_its_saved_step_reads_in_a(),
                _read(S3, "+", S2, ReadChannel.TEXT),
            }
        ),
        None,
    )


def test_e12_an_added_form_field_and_its_read_are_effects() -> None:
    saved, final = _edit(
        "edit_seed_a.json",
        *_keep(1, 2),
        ModifyExistingStep(
            existing_step_ref=S3,
            input_source="previous_step",
            input_type="text",
            uses_form_fields=["sokande", "sokt_belopp", "handlaggare"],
        ),
        form_fields=[
            # The saved fields restated as saved; the seed also records an order.
            *(
                FlowInputFieldIntent.model_validate(
                    {key: value for key, value in field.items() if key != "order"}
                )
                for field in _seed("edit_seed_a.json")["metadata_json"]["form_schema"][
                    "fields"
                ]
            ),
            FlowInputFieldIntent(
                name="handlaggare", label="Handläggare", required=True
            ),
        ],
    )

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FormEffect("added", "handlaggare"),
                FieldEffect(S3, "input_bindings"),
                _read(
                    S3,
                    "+",
                    None,
                    ReadChannel.FORM_FIELD,
                    ("handlaggare",),
                    ReadSite.QUESTION,
                ),
                # The saved field reads became one read of the whole output.
                *_s3_loses_its_saved_step_reads_in_a(),
                _read(S3, "+", S2, ReadChannel.STRUCTURED),
            }
        ),
        None,
    )


def test_e16_a_removed_step_and_field_reads_replaced_by_a_whole_read() -> None:
    saved, final = _edit(
        "edit_seed_g.json",
        *_keep(1, 3),
        ModifyExistingStep(
            existing_step_ref=S4, input_source="previous_step", input_type="json"
        ),
        removed_existing_step_refs=frozenset({S2}),
    )

    # A JSON consumer's implicit read is the reader's STRUCTURED_ELSE_TEXT.
    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                StructureEffect("removed", S2),
                _read(S2, "-", S1, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
                FieldEffect(S4, "input_type"),
                FieldEffect(S4, "input_bindings"),
                FieldEffect(S4, "input_contract"),
                _read(
                    S4,
                    "-",
                    S1,
                    ReadChannel.STRUCTURED,
                    ("diarienummer",),
                    label="Diarienummer",
                ),
                _read(
                    S4, "-", S2, ReadChannel.STRUCTURED, ("belopp_kr",), label="Belopp"
                ),
                _read(
                    S4,
                    "-",
                    S2,
                    ReadChannel.STRUCTURED,
                    ("inom_bidragstak",),
                    label="Inom bidragstaket",
                ),
                _read(
                    S4,
                    "-",
                    S3,
                    ReadChannel.STRUCTURED,
                    ("sista_datum",),
                    label="Sista datum",
                ),
                _read(
                    S4,
                    "+",
                    S3,
                    ReadChannel.STRUCTURED_ELSE_TEXT,
                    site=ReadSite.IMPLICIT,
                ),
            }
        ),
        None,
    )


def test_an_inserted_step_is_named_by_its_plan_ref_and_displaces_a_positional_read() -> (
    None
):
    saved, final = _edit(
        "edit_seed_g.json",
        *_keep(1),
        AddStep(step=SemanticStepIntent(name="Granska", instructions="Granska.")),
        *_keep(2, 3, 4),
    )
    inserted = final.steps[1].plan_step_ref

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                StructureEffect("added", inserted),
                _read(inserted, "+", S1, ReadChannel.STRUCTURED),
                _read(S2, "-", S1, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
                _read(S2, "+", inserted, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
            }
        ),
        None,
    )


def test_e17_a_swap_keeps_reads_that_follow_their_producer() -> None:
    saved, final = _edit("edit_seed_g.json", *_keep(1, 3, 2, 4))

    # s3 and s4 name their producers: those reads move with them. s2 reads
    # its predecessor, which is now s3.
    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                _read(S2, "-", S1, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
                _read(S2, "+", S3, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
            }
        ),
        OrderEffect(saved=(S1, S2, S3, S4), final=(S1, S3, S2, S4)),
    )


@pytest.mark.parametrize(
    ("moved", "matches"),
    [
        ({S2, S3}, True),
        ({S3}, True),
        ({S2}, True),
        (set(), False),  # an undeclared reorder
        ({S4}, False),  # s2 and s3 still change places
        ({S1, S3}, False),  # s1 did not move
    ],
)
def test_e17_the_order_matches_only_a_moved_set_that_explains_it(
    moved: set[str], matches: bool
) -> None:
    saved, final = _edit("edit_seed_g.json", *_keep(1, 3, 2, 4))

    assert (
        order_matches_moves(edit_effect(saved, final).order, frozenset(moved))
        is matches
    )


@pytest.mark.parametrize(
    ("order", "moved", "matches"),
    [
        (None, set(), True),
        (None, {S2}, False),  # a declared move that did not happen
        (OrderEffect(saved=(S1, S2, S3, S4), final=(S4, S1, S2, S3)), {S4}, True),
    ],
)
def test_the_order_check_without_a_reorder_and_for_a_move_to_the_start(
    order: OrderEffect | None, moved: set[str], matches: bool
) -> None:
    assert order_matches_moves(order, frozenset(moved)) is matches


BELOPP_IN_INSTRUCTIONS = "\n\nBelopp: {{ step_2.output.structured.belopp_kr }}"


def _seed_g_with_s4_instructions_reading_s2() -> dict[str, Any]:
    seed = _seed("edit_seed_g.json")
    seed["steps"][3]["instructions"] += BELOPP_IN_INSTRUCTIONS
    return seed


def test_an_instruction_read_follows_its_producer_through_a_reorder() -> None:
    saved, final = _edit(_seed_g_with_s4_instructions_reading_s2(), *_keep(1, 3, 2, 4))

    assert edit_effect(saved, final).effects == {
        _read(S2, "-", S1, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
        _read(S2, "+", S3, ReadChannel.TEXT, site=ReadSite.IMPLICIT),
    }


def test_an_instruction_read_removed_with_its_template() -> None:
    seed = _seed_g_with_s4_instructions_reading_s2()
    saved, final = _edit(
        seed,
        *_keep(1, 2, 3),
        ModifyExistingStep(
            existing_step_ref=S4,
            assistant_spec=AssistantSpecPatch(
                instructions=_seed("edit_seed_g.json")["steps"][3]["instructions"]
            ),
        ),
    )

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FieldEffect(S4, "instructions"),
                _read(
                    S4,
                    "-",
                    S2,
                    ReadChannel.STRUCTURED,
                    ("belopp_kr",),
                    ReadSite.INSTRUCTIONS,
                ),
            }
        ),
        None,
    )


def test_an_instruction_read_added_with_its_template() -> None:
    seed = _seed("edit_seed_g.json")
    saved, final = _edit(
        seed,
        *_keep(1, 2),
        ModifyExistingStep(
            existing_step_ref=S3,
            assistant_spec=AssistantSpecPatch(
                instructions=seed["steps"][2]["instructions"]
                + "\n\nÅtgärd: {{ step_1.output.structured.atgard }}"
            ),
        ),
        *_keep(4),
    )

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FieldEffect(S3, "instructions"),
                _read(
                    S3,
                    "+",
                    S1,
                    ReadChannel.STRUCTURED,
                    ("atgard",),
                    ReadSite.INSTRUCTIONS,
                ),
            }
        ),
        None,
    )


def test_a_read_whose_label_alone_changes_is_one_removed_and_one_added_read() -> None:
    saved, final = _edit("edit_seed_g.json", *_keep(1, 2, 3, 4))
    final = _with_source_ref(final, S4, 0, label="Ärende")

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FieldEffect(S4, "input_bindings"),
                _read(
                    S4,
                    "-",
                    S1,
                    ReadChannel.STRUCTURED,
                    ("diarienummer",),
                    label="Diarienummer",
                ),
                _read(
                    S4,
                    "+",
                    S1,
                    ReadChannel.STRUCTURED,
                    ("diarienummer",),
                    label="Ärende",
                ),
            }
        ),
        None,
    )


def test_a_read_whose_item_template_alone_changes_is_one_removed_and_one_added_read() -> (
    None
):
    seed = _seed("edit_seed_a.json")
    seed["steps"][2]["input_bindings"]["source_refs"].append(
        {
            "step_ref": "step_2",
            "output": "structured",
            "field_path": "saknade_falt",
            "item_template": "- {falt}",
        }
    )
    saved, final = _edit(seed, *_keep(1, 2, 3))
    final = _with_source_ref(final, S3, 4, item_template="* {falt}")
    missing = (S2, ReadChannel.STRUCTURED, ("saknade_falt",))

    assert edit_effect(saved, final) == EditEffect(
        frozenset(
            {
                FieldEffect(S3, "input_bindings"),
                _read(S3, "-", *missing, item_template="- {falt}"),
                _read(S3, "+", *missing, item_template="* {falt}"),
            }
        ),
        None,
    )


def test_the_document_body_writer_is_an_effect_by_identity() -> None:
    seed = {
        "name": "Rapport",
        "description": "",
        "metadata_json": {},
        "steps": [
            {
                "name": "Skriv rapporten",
                "instructions": "Skriv rapporten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_mode": "compose_text",
                "output_type": "text",
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa PDF.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "render_verbatim",
                "output_type": "pdf",
            },
        ],
    }
    saved, final = _edit(seed, *_keep(1, 2))

    # The saved writer is existing_step_1 and the compiled one step_a: one step.
    assert saved.document_body_writer_step_refs == (S1,)
    assert final.document_body_writer_step_refs == ("step_a",)
    assert edit_effect(saved, final) == EditEffect(frozenset(), None)
    cleared = final.model_copy(update={"document_body_writer_step_refs": None})
    assert edit_effect(saved, cleared) == EditEffect(
        frozenset({DocumentBodyWriterEffect("removed", S1)}), None
    )
