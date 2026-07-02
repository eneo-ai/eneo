"""Tests for the dynamic edit-mode tool schema builder."""

from __future__ import annotations

from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
    builder_input_type_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import SemanticStepIntent
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import FlowMcpPolicy


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
        mcp_policy="inherit",
    )


def _catalog_with_models(
    models: list[AIBuilderAvailableModelResource],
) -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=models,
        available_kbs=[],
        available_mcps=[],
    )


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


def _modify_step_schema(schema):
    step_variants = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "oneOf"
    ]
    return next(
        variant
        for variant in step_variants
        if variant["properties"]["kind"]["enum"] == ["modify"]
    )


def _add_step_payload_schema(schema):
    step_variants = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "oneOf"
    ]
    add_schema = next(
        variant
        for variant in step_variants
        if variant["properties"]["kind"]["enum"] == ["add"]
    )
    return add_schema["properties"]["step"]


class TestBuildEditFlowToolSchema:
    def test_schema_has_correct_name(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )
        assert schema["function"]["name"] == PROPOSE_FLOW_TOOL_NAME
        assert "complete ordered step list" in schema["function"]["description"]
        assert "removed_existing_step_refs" in schema["function"]["description"]

    def test_schema_uses_flat_ordered_edit_contract(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1), _make_step(2)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        params = schema["function"]["parameters"]
        props = params["properties"]
        assert "steps" in props
        assert "removed_existing_step_refs" in props
        assert "operations" not in props
        assert "form_operations" not in props

        step_item = props["steps"]["items"]
        serialized = str(step_item)
        assert "existing_step_ref" in serialized
        assert "existing_step_1" in serialized
        assert "kind" in serialized
        assert "modify" in serialized
        assert "add" in serialized
        assert "placement" not in serialized
        assert "patch" not in serialized

    def test_schema_exposes_direct_flow_metadata_fields_not_metadata_patch(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        properties = schema["function"]["parameters"]["properties"]
        assert "flow_name" in properties
        assert "flow_description" in properties
        assert "metadata_patch" not in properties

    def test_add_step_payload_hides_runtime_input_constraints(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)
        properties = add_payload["properties"]
        assert "runtime_required" not in properties
        assert "runtime_max_files" not in properties

    def test_existing_step_ref_enum_contains_valid_refs(self):
        steps = [_make_step(1), _make_step(2), _make_step(3)]
        schema = build_edit_flow_tool_schema(
            steps,
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        existing_ref = _modify_step_schema(schema)["properties"]["existing_step_ref"]
        assert existing_ref["enum"] == [
            "existing_step_1",
            "existing_step_2",
            "existing_step_3",
        ]

    def test_removed_existing_step_refs_match_valid_refs(self):
        steps = [_make_step(1), _make_step(2)]
        schema = build_edit_flow_tool_schema(
            steps,
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        removed_refs = schema["function"]["parameters"]["properties"][
            "removed_existing_step_refs"
        ]
        assert removed_refs["items"]["enum"] == [
            "existing_step_1",
            "existing_step_2",
        ]

    def test_model_refs_injected_when_small(self):
        catalog = _catalog_with_models(
            [
                {
                    "id": "model_a",
                    "ref": "model_a",
                    "name": "model_a",
                    "display_name": "model_a",
                    "provider": "test",
                },
                {
                    "id": "model_b",
                    "ref": "model_b",
                    "name": "model_b",
                    "display_name": "model_b",
                    "provider": "test",
                },
            ]
        )
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)
        model_ref = add_payload["properties"]["model_ref"]
        assert "enum" in model_ref
        assert "model.model-a" in model_ref["enum"]

    def test_model_refs_not_injected_when_large(self):
        catalog = _catalog_with_models(
            [
                {
                    "id": f"model_{i}",
                    "ref": f"model_{i}",
                    "name": f"model_{i}",
                    "display_name": f"model_{i}",
                    "provider": "test",
                }
                for i in range(20)
            ]
        )
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)
        model_ref = add_payload["properties"]["model_ref"]
        assert "enum" not in model_ref

    def test_step_kind_variants_are_add_and_modify(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )
        variants = schema["function"]["parameters"]["properties"]["steps"]["items"][
            "oneOf"
        ]
        assert [variant["properties"]["kind"]["enum"][0] for variant in variants] == [
            "modify",
            "add",
        ]

    def test_form_fields_schema_teaches_complete_state_edits(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        form_fields = schema["function"]["parameters"]["properties"]["form_fields"]
        item_schema = form_fields["items"]
        properties = item_schema["properties"]

        assert item_schema["additionalProperties"] is False
        assert item_schema["required"] == ["name", "type", "label"]
        assert set(properties) == {
            "name",
            "type",
            "label",
            "required",
            "options",
        }
        assert properties["type"]["enum"] == [
            "text",
            "number",
            "date",
            "select",
            "multiselect",
        ]
        assert properties["options"] == {
            "type": ["array", "null"],
            "items": {"type": "string"},
        }
        description = form_fields["description"]
        assert "Omit to preserve" in description
        assert "set null to clear all" in description

    def test_add_payload_exposes_shared_semantic_step_shape(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)

        assert "assistant_spec" not in add_payload["properties"]
        assert "input_source" not in add_payload["properties"]
        assert "output_mode" not in add_payload["properties"]
        assert "input_bindings" not in add_payload["properties"]
        assert "output_contract" not in add_payload["properties"]
        assert "output_config" not in add_payload["properties"]
        assert "input_type" not in add_payload["properties"]
        assert "runtime_required" not in add_payload["properties"]
        assert "runtime_max_files" not in add_payload["properties"]
        assert "document_delivery_mode" not in add_payload["properties"]
        assert "instructions" in add_payload["properties"]
        assert "output_fields" in add_payload["properties"]
        assert "uses_previous_fields" not in add_payload["properties"]
        assert add_payload["properties"]["review_mode"]["enum"] == [
            "view",
            "edit",
            None,
        ]

    def test_add_payload_schema_tracks_shared_semantic_step_intent_fields(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)

        assert set(add_payload["properties"]) == set(SemanticStepIntent.model_fields)

    def test_mcp_refs_are_exposed_without_schema_enums_on_add_and_patch_payloads(
        self,
    ):
        catalog = build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            available_mcps=[
                {
                    "ref": "server-1",
                    "tools": [{"ref": "tool-1", "name": "lookup_case"}],
                }
            ],
        )
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)
        modify_step = _modify_step_schema(schema)

        assert "enum" not in add_payload["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in add_payload["properties"]["mcp_tool_refs"]["items"]
        assistant_spec = modify_step["properties"]["assistant_spec"]
        assert "enum" not in assistant_spec["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in assistant_spec["properties"]["mcp_tool_refs"]["items"]

    def test_mcp_refs_stay_free_form_with_empty_or_malformed_resources(self):
        catalog = build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            available_mcps=[
                {"ref": "", "tools": [{"ref": "ignored-tool"}]},
                {
                    "ref": "server-1",
                    "tools": [
                        {"ref": ""},
                        {"ref": " "},
                        {"ref": "tool-1", "name": "lookup_case"},
                    ],
                },
            ],
        )
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            resource_catalog=catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )

        add_payload = _add_step_payload_schema(schema)

        assert "enum" not in add_payload["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in add_payload["properties"]["mcp_tool_refs"]["items"]

    def test_modify_step_schema_exposes_typed_previous_field_refs(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1), _make_step(2)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )
        modify_step = _modify_step_schema(schema)

        previous_fields = modify_step["properties"]["uses_previous_fields"]
        assert previous_fields["items"]["required"] == ["from_step", "field_path"]
        assert "input_bindings" not in modify_step["properties"]
        assert "input_contract" not in modify_step["properties"]
        assert "input_config" not in modify_step["properties"]
        assert "output_config" not in modify_step["properties"]
        assert "output_contract" in modify_step["properties"]
        assert "uses_form_fields" in modify_step["properties"]

    def test_modify_step_schema_uses_generated_flow_schema_values(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1), _make_step(2)],
            resource_catalog=_empty_catalog(),
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )
        props = _modify_step_schema(schema)["properties"]

        assert props["input_source"]["enum"] == [*builder_input_source_values(), None]
        assert props["input_type"]["enum"] == [*builder_input_type_values(), None]
        assert "output_mode" not in props
        assert props["output_type"]["enum"] == [*builder_output_type_values(), None]
        assert props["document_delivery_mode"]["enum"] == [
            *document_delivery_mode_values(),
            None,
        ]
        assert props["mcp_policy"]["enum"] == [
            *(policy.value for policy in FlowMcpPolicy),
            None,
        ]
        assert props["review_mode"]["enum"] == ["view", "edit", None]
