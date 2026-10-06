"""Local command admission preserves identity without inferring model intent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_edit_admission import (
    EditCommandRejection,
    lower_edit_commands,
    parse_edit_commands,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import AddStep, ModifyExistingStep

BASELINE = {
    "existing_step_1": "Extract",
    "existing_step_2": "Check",
    "existing_step_3": "Write",
}


def _modify(ref="existing_step_2", **fields):
    return {"kind": "modify", "existing_step_ref": ref, **fields}


def _add(local_id="new", placement=None, **fields):
    return {
        "kind": "add",
        "local_id": local_id,
        "placement": placement or {"kind": "start"},
        "step": {
            "name": "New assessment",
            "instructions": "Assess the evidence.",
            **fields,
        },
    }


def _saved(ref):
    return {"kind": "saved", "existing_step_ref": ref}


def _after(target):
    return {"kind": "after", "target": target}


def _lower(operations, **root):
    return lower_edit_commands(
        parse_edit_commands(
            {
                "plan_rationale": "Change only the requested work.",
                "operations": operations,
                **root,
            }
        ),
        baseline_names=BASELINE,
    )


@pytest.mark.parametrize("strict", [False, True])
def test_untouched_steps_and_null_patches_are_kept(strict):
    """Mutants: drop an omitted saved row; treat keep-null as clear."""
    patch = _modify(name="Changed")
    if strict:
        patch.update(
            output_fields=None,
            review_mode=None,
            assistant_spec={"instructions": None, "knowledge_refs": None},
        )
    operations = [patch]
    if strict:
        operations.append(
            {
                "kind": "modify_flow",
                "flow_name": None,
                "flow_description": None,
                "form_fields": None,
            }
        )
    proposal = _lower(operations)
    assert [step.existing_step_ref for step in proposal.steps] == list(BASELINE)
    assert [step.authored_fields for step in proposal.steps] == [
        frozenset(),
        frozenset({"name"}),
        frozenset(),
    ]
    assert not proposal.model_fields_set.intersection({"flow_name", "form_fields"})


def test_explicit_clear_and_provider_field_tree_survive_lowering():
    """Mutants: clear becomes keep; object children lowered as array members."""
    proposal = _lower(
        [
            _modify(
                review_mode="none",
                uses_form_fields=[],
                output_fields=[
                    {
                        "name": "facts",
                        "field_type": "object",
                        "description": "Evidence",
                        "children": [
                            {
                                "name": "date",
                                "field_type": "string",
                                "description": "Received date",
                            }
                        ],
                    }
                ],
            )
        ]
    )
    step = proposal.steps[1]
    assert isinstance(step, ModifyExistingStep)
    assert step.review_mode is None and "review_mode" in step.authored_fields
    assert step.uses_form_fields == [] and "uses_form_fields" in step.authored_fields
    assert step.output_fields and step.output_fields[0].fields[0].name == "date"


@pytest.mark.parametrize(
    ("operations", "expected", "removed"),
    [
        (
            [_add()],
            [None, "existing_step_1", "existing_step_2", "existing_step_3"],
            set(),
        ),
        (
            [
                {
                    "kind": "move",
                    "existing_step_ref": "existing_step_3",
                    "placement": {"kind": "start"},
                }
            ],
            ["existing_step_3", "existing_step_1", "existing_step_2"],
            set(),
        ),
        (
            [{"kind": "remove", "existing_step_ref": "existing_step_2"}],
            ["existing_step_1", "existing_step_3"],
            {"existing_step_2"},
        ),
        (
            [
                _modify(name="Changed"),
                {
                    "kind": "move",
                    "existing_step_ref": "existing_step_2",
                    "placement": {"kind": "start"},
                },
            ],
            ["existing_step_2", "existing_step_1", "existing_step_3"],
            set(),
        ),
        (
            [
                _add(),
                _add(
                    "second",
                    _after({"kind": "added", "local_id": "new"}),
                    name="Second new",
                ),
            ],
            [None, None, "existing_step_1", "existing_step_2", "existing_step_3"],
            set(),
        ),
    ],
)
def test_topology_changes_only_through_explicit_commands(operations, expected, removed):
    """Mutants: infer removal/reorder; lose modify when move follows; reverse adds."""
    before = dict(BASELINE)
    proposal = _lower(operations)
    assert [
        step.existing_step_ref if isinstance(step, ModifyExistingStep) else None
        for step in proposal.steps
    ] == expected
    assert proposal.removed_existing_step_refs == removed
    assert BASELINE == before


@pytest.mark.parametrize(
    ("operations", "reason"),
    [
        ([_modify("missing")], "unknown_edit_step"),
        ([_modify(), _modify()], "duplicate_edit_operation"),
        (
            [
                {"kind": "modify_flow", "flow_name": "Changed"},
                {"kind": "modify_flow", "form_fields": []},
            ],
            "duplicate_edit_operation",
        ),
        (
            [_modify(), {"kind": "remove", "existing_step_ref": "existing_step_2"}],
            "conflicting_edit_operations",
        ),
        ([_add(), _add()], "duplicate_local_step"),
        (
            [_add(placement=_after({"kind": "added", "local_id": "later"}))],
            "unknown_edit_anchor",
        ),
        (
            [
                {
                    "kind": "move",
                    "existing_step_ref": "existing_step_2",
                    "placement": _after(_saved("existing_step_2")),
                }
            ],
            "self_edit_move",
        ),
        (
            [
                _add(placement=_after(_saved("existing_step_2"))),
                {"kind": "remove", "existing_step_ref": "existing_step_2"},
            ],
            "removed_edit_anchor",
        ),
        ([_add(name="  EXTRACT  ")], "edit_step_name_collision"),
        (
            [
                _add(
                    uses_previous_fields=[
                        {"producer": _saved("existing_step_3"), "field_path": "facts"}
                    ]
                )
            ],
            "invalid_edit_read",
        ),
    ],
)
def test_invalid_command_set_refuses_atomically(operations, reason):
    """Mutants: guess anchor/identity, accept collision, partially mutate baseline."""
    before = dict(BASELINE)
    with pytest.raises(EditCommandRejection) as error:
        _lower(operations)
    assert error.value.reason == reason
    assert BASELINE == before


@pytest.mark.parametrize(
    ("operations", "kind", "refs"),
    [
        ([_add(name="  EXTRACT  ")], "saved", ["existing_step_1"]),
        (
            [_modify(name="Renamed"), _add(name="Renamed")],
            "saved",
            ["existing_step_2"],
        ),
        ([_add(), _add(local_id="second")], "added", ["new"]),
    ],
)
def test_name_collision_feedback_identifies_the_conflicting_targets(
    operations, kind, refs
):
    """Mutants: lose saved aliases; describe a duplicate new add as saved work."""
    with pytest.raises(EditCommandRejection) as error:
        _lower(operations)
    assert error.value.reason == "edit_step_name_collision"
    assert f'"kind": "{kind}"' in str(error.value)
    assert all(ref in str(error.value) for ref in refs)


def test_identity_reads_lower_after_all_topology_commands():
    """Mutant: interpret a saved producer as a guessed numeric position."""
    proposal = _lower(
        [
            _add(
                placement=_after(_saved("existing_step_2")),
                uses_previous_fields=[
                    {"producer": _saved("existing_step_1"), "field_path": "facts"}
                ],
            ),
            {
                "kind": "move",
                "existing_step_ref": "existing_step_1",
                "placement": _after(_saved("existing_step_2")),
            },
        ]
    )
    added = proposal.steps[2]
    assert isinstance(added, AddStep)
    assert added.step.uses_previous_fields[0].from_step == 2
    assert added.step.uses_previous_fields[0].field_path == "facts"


@pytest.mark.parametrize(
    "operation",
    [
        _modify(uses_previous_fields=[{"from_step": 1, "field_path": "facts"}]),
        _add(uses_previous_fields=[{"from_step": 1, "field_path": "facts"}]),
    ],
)
def test_edit_parser_refuses_positional_reads(operation):
    """Mutant: accept the removed positional wire alongside typed identities."""
    with pytest.raises(ValidationError):
        parse_edit_commands(
            {"plan_rationale": "Read evidence.", "operations": [operation]}
        )


@pytest.mark.parametrize(
    "removed_root",
    [
        {"steps": [_modify()]},
        {"flow_name": "Unrequested rename"},
        {"flow_description": "Unrequested description"},
        {"form_fields": []},
    ],
)
def test_removed_edit_wire_has_no_alias(removed_root):
    """Mutant: accept mutations outside the explicit command list."""
    with pytest.raises(ValidationError):
        parse_edit_commands(
            {
                "plan_rationale": "Old contract.",
                "operations": [_modify()],
                **removed_root,
            }
        )


@pytest.mark.parametrize(
    "fields", [{"flow_name": "Renamed"}, {"flow_description": ""}, {"form_fields": []}]
)
def test_explicit_flow_command_preserves_saved_steps(fields):
    """Mutant: drop the explicit flow change or change saved step fields."""
    proposal = _lower([{"kind": "modify_flow", **fields}])
    assert {name: getattr(proposal, name) for name in fields} == fields
    assert [step.existing_step_ref for step in proposal.steps] == list(BASELINE)
    assert all(not step.authored_fields for step in proposal.steps)
