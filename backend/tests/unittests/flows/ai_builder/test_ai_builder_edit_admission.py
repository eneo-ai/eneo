"""The strict-shaped edit wire contract lowers into one canonical proposal."""

from __future__ import annotations

from uuid import uuid4

import jsonschema
import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_edit_admission import lower_edit_tool_arguments
from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    ReviewEditScope,
    validate_review_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep,
    ModifyExistingStep,
    OrderedEditProposal,
    ProposalStructuredFieldIntent,
    build_create_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import (
    build_native_strict_tool_schema,
    validate_native_strict_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.domain.flow import FlowStep


def _step(order: int) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=order,
        user_description=f"Step {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


def _catalog():
    return build_ai_builder_resource_catalog(available_models=[], available_kbs=[])


def _edit_schema(step_count: int = 2):
    return build_edit_flow_tool_schema(
        [_step(order) for order in range(1, step_count + 1)],
        resource_catalog=_catalog(),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
    )


# Every property present, as a strict provider sends it; null keeps the value.
def _strict_modify(ref: str, **changes: object) -> dict[str, object]:
    return {
        "kind": "modify",
        "existing_step_ref": ref,
        "name": None,
        "assistant_spec": {"instructions": None, "knowledge_refs": None},
        "input_source": None,
        "input_type": None,
        "output_type": None,
        "document_delivery_mode": None,
        "uses_form_fields": None,
        "uses_previous_fields": None,
        "output_fields": None,
        "review_mode": None,
        **changes,
    }


def _strict_arguments(*steps: dict[str, object], **top: object) -> dict[str, object]:
    return {
        "plan_rationale": "Keep the flow as it is.",
        "assumptions": [],
        "flow_name": None,
        "flow_description": None,
        "steps": list(steps),
        "removed_existing_step_refs": [],
        "form_fields": None,
        **top,
    }


def test_the_edit_tool_schema_projects_into_the_native_strict_subset() -> None:
    schema = _edit_schema()
    strict = build_native_strict_tool_schema(schema)  # type: ignore[arg-type]
    validate_native_strict_schema(strict["function"]["parameters"])
    assert strict["function"]["strict"] is True
    # The semantic schema is the admission contract and stays untouched.
    assert "strict" not in schema["function"]


def test_a_strict_shaped_unchanged_step_lowers_to_an_untouched_modify() -> None:
    arguments = _strict_arguments(_strict_modify("existing_step_1"))
    validate_propose_flow_tool_arguments(
        arguments=arguments,  # type: ignore[arg-type]
        tool_schema=_edit_schema(1),  # type: ignore[arg-type]
    )

    proposal = OrderedEditProposal.model_validate(lower_edit_tool_arguments(arguments))

    assert proposal.model_fields_set == {
        "plan_rationale",
        "assumptions",
        "steps",
        "removed_existing_step_refs",
    }
    (step,) = proposal.steps
    assert isinstance(step, ModifyExistingStep)
    assert step.model_fields_set == {"kind", "existing_step_ref"}


def test_explicit_clears_survive_lowering_and_stay_distinct_from_keeps() -> None:
    arguments = _strict_arguments(
        _strict_modify(
            "existing_step_1",
            assistant_spec={"instructions": None, "knowledge_refs": []},
            uses_form_fields=[],
            output_fields=[],
            review_mode="none",
        ),
        form_fields=[],
        flow_description="",
    )

    proposal = OrderedEditProposal.model_validate(lower_edit_tool_arguments(arguments))

    assert proposal.form_fields == [] and "form_fields" in proposal.model_fields_set
    assert proposal.flow_description == ""
    (step,) = proposal.steps
    assert isinstance(step, ModifyExistingStep)
    assert step.assistant_spec is not None
    assert step.assistant_spec.model_fields_set == {"knowledge_refs"}
    assert step.assistant_spec.knowledge_refs == []
    assert step.uses_form_fields == []
    # An empty field list is admitted as "no structured contract".
    assert "output_fields" in step.model_fields_set and step.output_fields is None
    assert "review_mode" in step.model_fields_set and step.review_mode is None


def test_an_added_step_keeps_its_edit_only_fields_and_drops_keep_nulls() -> None:
    arguments = _strict_arguments(
        _strict_modify("existing_step_1"),
        {
            "kind": "add",
            "step": {
                "name": "Sammanställ",
                "instructions": "Sammanställ ärendet som JSON.",
                "output_type": "json",
                "output_fields": [
                    {
                        "name": "summary",
                        "field_type": "string",
                        "description": "Sammanfattning",
                        "required": True,
                        "nullable": False,
                        "children": None,
                    }
                ],
                "uses_form_fields": ["case_id"],
                "model_ref": None,
                "knowledge_refs": None,
                "citations_requested": False,
                "review_mode": "view",
            },
        },
    )
    validate_propose_flow_tool_arguments(
        arguments=arguments,  # type: ignore[arg-type]
        tool_schema=_edit_schema(1),  # type: ignore[arg-type]
    )

    proposal = OrderedEditProposal.model_validate(lower_edit_tool_arguments(arguments))

    added = proposal.steps[1]
    assert isinstance(added, AddStep)
    assert added.step.output_type == "json"
    assert added.step.uses_form_fields == ["case_id"]
    assert added.step.review_mode == "view"
    assert added.step.model_ref is None and added.step.knowledge_refs == []
    assert added.step.output_fields == [
        StructuredFieldDraft(
            name="summary", field_type="string", description="Sammanfattning"
        )
    ]


def test_the_field_tree_lowers_the_same_way_for_create_and_edit() -> None:
    tree = {
        "name": "items",
        "field_type": "array",
        "description": "Rows",
        "required": True,
        "nullable": False,
        "children": [
            {
                "name": "title",
                "field_type": "string",
                "description": "Title",
                "required": True,
                "nullable": True,
                "children": None,
            }
        ],
    }
    create_draft = ProposalStructuredFieldIntent.model_validate(
        tree
    ).to_structured_field_draft()

    modify = OrderedEditProposal.model_validate(
        lower_edit_tool_arguments(
            _strict_arguments(_strict_modify("existing_step_1", output_fields=[tree]))
        )
    ).steps[0]
    assert isinstance(modify, ModifyExistingStep)
    added = OrderedEditProposal.model_validate(
        lower_edit_tool_arguments(
            _strict_arguments(
                {
                    "kind": "add",
                    "step": {
                        "name": "Rows",
                        "instructions": "List the rows.",
                        "output_fields": [tree],
                    },
                }
            )
        )
    ).steps[0]
    assert isinstance(added, AddStep)

    assert modify.output_fields == [create_draft]
    assert added.step.output_fields == [create_draft]
    # And the create tool offers the very same field tree on the wire.
    create_items = build_create_flow_tool_schema(
        resource_catalog=_catalog(), tool_name=PROPOSE_FLOW_TOOL_NAME
    )["function"]["parameters"]["properties"]["steps"]["items"]["properties"][
        "output_fields"
    ]["items"]
    edit_items = _edit_schema(1)["function"]["parameters"]["properties"]["steps"][
        "items"
    ]["anyOf"][0]["properties"]["output_fields"]["items"]
    assert create_items == edit_items


def test_a_malformed_field_tree_is_a_validation_error_not_a_silent_drop() -> None:
    with pytest.raises(ValidationError):
        OrderedEditProposal.model_validate(
            lower_edit_tool_arguments(
                _strict_arguments(
                    _strict_modify(
                        "existing_step_1",
                        output_fields=[{"name": "summary", "field_type": "text"}],
                    )
                )
            )
        )


def test_a_scoped_strict_payload_lowers_to_what_the_findings_allow() -> None:
    # The scoped schema lists untouched steps as keep and offers no flow-level
    # fields; the lowered proposal must read as touching only the findings'
    # step, so the scope check has nothing to refuse.
    scope = ReviewEditScope(
        step_refs=frozenset({"existing_step_2"}),
        removable_step_refs=frozenset(),
        may_add=False,
    )
    schema = build_edit_flow_tool_schema(
        [_step(1), _step(2), _step(3)],
        resource_catalog=_catalog(),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        review_scope=scope,
    )
    arguments: dict[str, object] = {
        "plan_rationale": "Tighten step 2's instructions.",
        "assumptions": [],
        "steps": [
            {"kind": "keep", "existing_step_ref": "existing_step_1"},
            _strict_modify(
                "existing_step_2",
                assistant_spec={
                    "instructions": "Read the source and cite it.",
                    "knowledge_refs": None,
                },
            ),
            {"kind": "keep", "existing_step_ref": "existing_step_3"},
        ],
    }
    validate_propose_flow_tool_arguments(
        arguments=arguments,  # type: ignore[arg-type]
        tool_schema=schema,  # type: ignore[arg-type]
    )
    strict = build_native_strict_tool_schema(schema)  # type: ignore[arg-type]
    jsonschema.validate(arguments, strict["function"]["parameters"])

    proposal = OrderedEditProposal.model_validate(lower_edit_tool_arguments(arguments))

    kept = [step for step in proposal.steps if isinstance(step, ModifyExistingStep)]
    assert [step.existing_step_ref for step in kept] == [
        "existing_step_1",
        "existing_step_2",
        "existing_step_3",
    ]
    assert kept[0].model_fields_set == {"kind", "existing_step_ref"}
    assert kept[2].model_fields_set == {"kind", "existing_step_ref"}
    assert kept[1].assistant_spec is not None
    assert (
        validate_review_edit_proposal(
            scope=scope,
            proposal=proposal,
            flow_name="Flow",
            flow_description="Current description",
            current_step_refs=["existing_step_1", "existing_step_2", "existing_step_3"],
        )
        is None
    )
