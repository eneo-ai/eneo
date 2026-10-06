"""One edit grammar offers exactly the current scope's typed operations."""

from __future__ import annotations

from uuid import uuid4

import jsonschema
import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_edit_admission import parse_edit_commands
from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_flow_review import ReviewEditScope
from eneo.flows.ai_builder.ai_builder_plan_edit_context import EditOperationPermissions
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import (
    build_native_strict_tool_schema,
    validate_native_strict_schema,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_capability_manifest import CapabilityProjection, projection_values


def _make_step(step_order: int) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


def _schema(step_count=3, **scope):
    return build_edit_flow_tool_schema(
        [_make_step(order) for order in range(1, step_count + 1)],
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        **scope,
    )


def _branches(schema):
    item = schema["function"]["parameters"]["properties"]["operations"]["items"]
    branches = item.get("anyOf", [item])
    return {branch["properties"]["kind"]["enum"][0]: branch for branch in branches}


def test_local_edit_does_not_require_model_authored_keeps() -> None:
    """Mutant: retain the complete-list edit wire or an old-wire alias."""
    schema = _schema(30)["function"]["parameters"]
    jsonschema.validate(
        {
            "plan_rationale": "Rename only the selected step.",
            "operations": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_17",
                    "name": "Changed",
                }
            ],
        },
        schema,
    )
    assert "steps" not in schema["properties"]
    assert "removed_existing_step_refs" not in schema["properties"]
    assert not {"flow_name", "flow_description", "form_fields"}.intersection(
        schema["properties"]
    )


@pytest.mark.parametrize(
    ("scope", "kinds", "refs", "removable"),
    [
        (
            {},
            {"modify", "add", "remove", "move", "modify_flow"},
            ["existing_step_1", "existing_step_2", "existing_step_3"],
            ["existing_step_1", "existing_step_2", "existing_step_3"],
        ),
        (
            {
                "permissions": EditOperationPermissions(
                    step_refs=frozenset({"existing_step_2"}),
                    removable_step_refs=frozenset(),
                    may_add=False,
                )
            },
            {"modify"},
            ["existing_step_2"],
            [],
        ),
        (
            {
                "review_scope": ReviewEditScope(
                    step_refs=frozenset({"existing_step_2"}),
                    removable_step_refs=frozenset({"existing_step_2"}),
                    may_add=True,
                )
            },
            {"modify", "add", "remove"},
            ["existing_step_2"],
            ["existing_step_2"],
        ),
    ],
)
def test_scopes_offer_only_permitted_operations(scope, kinds, refs, removable):
    """Mutants: leak whole-flow targets/topology or metadata into a scoped turn."""
    schema = _schema(**scope)
    branches = _branches(schema)
    assert set(branches) == kinds
    assert branches["modify"]["properties"]["existing_step_ref"]["enum"] == refs
    if removable:
        assert (
            branches["remove"]["properties"]["existing_step_ref"]["enum"] == removable
        )
    if scope:
        assert set(schema["function"]["parameters"]["properties"]) == {
            "operations",
            "plan_rationale",
            "assumptions",
        }
    strict = build_native_strict_tool_schema(schema)
    validate_native_strict_schema(strict["function"]["parameters"])


@pytest.mark.parametrize(
    "operation",
    [
        {
            "kind": "modify",
            "existing_step_ref": "existing_step_1",
            "assistant_spec": {"instructions": "Compare the evidence."},
        },
        {
            "kind": "add",
            "local_id": "assessment",
            "placement": {
                "kind": "after",
                "target": {"kind": "saved", "existing_step_ref": "existing_step_1"},
            },
            "step": {
                "name": "Assessment",
                "instructions": "Assess the facts.",
                "uses_previous_fields": [
                    {
                        "producer": {
                            "kind": "saved",
                            "existing_step_ref": "existing_step_1",
                        },
                        "field_path": "facts",
                    }
                ],
            },
        },
        {
            "kind": "move",
            "existing_step_ref": "existing_step_2",
            "placement": {"kind": "start"},
        },
        {"kind": "remove", "existing_step_ref": "existing_step_2"},
        {"kind": "modify_flow", "flow_description": "", "form_fields": []},
    ],
)
def test_schema_and_parser_share_the_command_contract(operation):
    """Mutant: schema admits a branch the typed parser cannot represent."""
    arguments = {
        "plan_rationale": "Change the requested work.",
        "operations": [operation],
    }
    jsonschema.validate(arguments, _schema()["function"]["parameters"])
    assert parse_edit_commands(arguments).operations[0].kind == operation["kind"]


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "keep", "existing_step_ref": "existing_step_1"},
        {
            "kind": "modify",
            "existing_step_ref": "existing_step_1",
            "assistant_spec": {"model_ref": "other"},
        },
        {
            "kind": "modify",
            "existing_step_ref": "existing_step_1",
            "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
        },
        {
            "kind": "add",
            "local_id": "new",
            "placement": {"kind": "start"},
            "step": {"name": "New", "instructions": "Assess.", "model_ref": "other"},
        },
        {
            "kind": "add",
            "local_id": "new",
            "placement": {"kind": "start"},
            "step": {
                "name": "New",
                "instructions": "Assess.",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
        },
    ],
)
def test_model_switch_and_removed_wire_are_refused(operation):
    """Mutants: expose model policy or retain positional/keep aliases."""
    arguments = {"plan_rationale": "Invalid proposal.", "operations": [operation]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(arguments, _schema()["function"]["parameters"])
    with pytest.raises(ValidationError):
        parse_edit_commands(arguments)


def test_new_and_saved_steps_use_their_own_capability_vocabulary(monkeypatch):
    """Mutant: use editable-existing capabilities for newly proposed steps."""
    from eneo.flows import flow_capability_manifest as manifest

    real = manifest.projection_cells

    def without_pdf_proposals(projection):
        cells = real(projection)
        return (
            frozenset(cell for cell in cells if cell[2].value != "pdf")
            if projection is CapabilityProjection.PROPOSABLE_NEW
            else cells
        )

    monkeypatch.setattr(manifest, "projection_cells", without_pdf_proposals)
    branches = _branches(_schema())
    assert (
        "pdf"
        not in branches["add"]["properties"]["step"]["properties"]["output_type"][
            "enum"
        ]
    )
    modified = branches["modify"]["properties"]
    assert modified["output_type"]["enum"] == [
        *projection_values(CapabilityProjection.EDITABLE_EXISTING, "output_type"),
        None,
    ]
    assert "pdf" in modified["output_type"]["enum"]
    assert not set(modified).intersection(
        {
            "output_mode",
            "input_bindings",
            "output_contract",
            "output_config",
            "input_config",
        }
    )
