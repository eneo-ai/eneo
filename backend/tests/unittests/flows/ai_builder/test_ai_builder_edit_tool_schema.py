"""Tests for the dynamic edit-mode tool schema builder."""

from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_edit_tool_schema import (
    EDIT_FLOW_TOOL_NAME,
    build_edit_flow_tool_schema,
    build_edit_mode_tool_schemas,
)
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
    builder_input_type_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from intric.flows.flow import FlowStep


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


class TestBuildEditFlowToolSchema:
    def test_schema_has_correct_name(self):
        schema = build_edit_flow_tool_schema([_make_step(1)])
        assert schema["function"]["name"] == EDIT_FLOW_TOOL_NAME
        assert "form_operations" in schema["function"]["description"]
        assert "uses_form_fields" in schema["function"]["description"]

    def test_target_ref_enum_contains_valid_refs(self):
        steps = [_make_step(1), _make_step(2), _make_step(3)]
        schema = build_edit_flow_tool_schema(steps)

        ops_schema = schema["function"]["parameters"]["properties"]["operations"]
        target_ref = ops_schema["items"]["properties"]["target_ref"]
        assert "existing_step_1" in target_ref["enum"]
        assert "existing_step_2" in target_ref["enum"]
        assert "existing_step_3" in target_ref["enum"]
        assert None in target_ref["enum"]

    def test_anchor_ref_enum_matches_valid_refs(self):
        steps = [_make_step(1), _make_step(2)]
        schema = build_edit_flow_tool_schema(steps)

        ops_schema = schema["function"]["parameters"]["properties"]["operations"]
        placement = ops_schema["items"]["properties"]["placement"]
        anchor_ref = placement["properties"]["anchor_ref"]
        assert "existing_step_1" in anchor_ref["enum"]
        assert "existing_step_2" in anchor_ref["enum"]

    def test_model_refs_injected_when_small(self):
        models = [{"ref": "model_a"}, {"ref": "model_b"}]
        schema = build_edit_flow_tool_schema([_make_step(1)], available_models=models)

        add_payload = schema["function"]["parameters"]["properties"]["operations"][
            "items"
        ]["properties"]["add_payload"]
        model_ref = add_payload["properties"]["model_ref"]
        assert "enum" in model_ref
        assert "model.model-a" in model_ref["enum"]

    def test_model_refs_not_injected_when_large(self):
        models = [{"ref": f"model_{i}"} for i in range(20)]
        schema = build_edit_flow_tool_schema([_make_step(1)], available_models=models)

        add_payload = schema["function"]["parameters"]["properties"]["operations"][
            "items"
        ]["properties"]["add_payload"]
        model_ref = add_payload["properties"]["model_ref"]
        assert "enum" not in model_ref

    def test_op_enum_is_add_modify_remove(self):
        schema = build_edit_flow_tool_schema([_make_step(1)])
        ops_schema = schema["function"]["parameters"]["properties"]["operations"]
        op_field = ops_schema["items"]["properties"]["op"]
        assert op_field["enum"] == ["add", "modify", "remove"]

    def test_form_operations_schema_teaches_form_field_edits(self):
        schema = build_edit_flow_tool_schema([_make_step(1)])

        form_operations = schema["function"]["parameters"]["properties"][
            "form_operations"
        ]
        item_schema = form_operations["items"]
        properties = item_schema["properties"]
        payload = properties["field_payload"]

        assert item_schema["additionalProperties"] is False
        assert properties["op"]["enum"] == ["add", "modify", "remove"]
        assert item_schema["required"] == ["op", "field_name"]
        assert properties["field_name"] == {"type": "string", "minLength": 1}
        assert set(payload["properties"]) == {
            "label",
            "field_type",
            "required",
            "description",
            "options",
        }
        assert payload["additionalProperties"] is False
        assert payload["properties"]["field_type"]["enum"] == [
            "text",
            "number",
            "date",
            "select",
            "multiselect",
        ]
        assert payload["properties"]["options"] == {
            "type": "array",
            "items": {"type": "string"},
        }
        description = form_operations["description"]
        assert "uses_form_fields" in description
        assert "orphan UI controls" in description
        assert "field_payload is required for add and modify" in description
        assert "omit field_payload for remove" in description

    def test_add_payload_uses_shared_new_step_authoring_shape(self):
        schema = build_edit_flow_tool_schema([_make_step(1)])

        add_payload = schema["function"]["parameters"]["properties"]["operations"][
            "items"
        ]["properties"]["add_payload"]

        assert "assistant_spec" not in add_payload["properties"]
        assert "output_mode" not in add_payload["properties"]
        assert "input_bindings" not in add_payload["properties"]
        assert "output_contract" not in add_payload["properties"]
        assert "output_config" not in add_payload["properties"]
        assert "instructions" in add_payload["properties"]
        assert "document_delivery_mode" in add_payload["properties"]
        assert "output_fields" in add_payload["properties"]
        previous_fields = add_payload["properties"]["uses_previous_fields"]
        assert previous_fields["items"]["required"] == ["from_step", "field_path"]
        assert add_payload["properties"]["review_mode"]["enum"] == [
            "view",
            "edit",
            None,
        ]

    def test_mcp_refs_are_exposed_without_schema_enums_on_add_and_patch_payloads(
        self,
    ):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
            available_mcps=[
                {
                    "ref": "server-1",
                    "tools": [{"ref": "tool-1", "name": "lookup_case"}],
                }
            ],
        )

        add_payload = schema["function"]["parameters"]["properties"]["operations"][
            "items"
        ]["properties"]["add_payload"]
        patch = schema["function"]["parameters"]["properties"]["operations"]["items"][
            "properties"
        ]["patch"]

        assert "enum" not in add_payload["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in add_payload["properties"]["mcp_tool_refs"]["items"]
        assistant_spec = patch["properties"]["assistant_spec"]
        assert "enum" not in assistant_spec["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in assistant_spec["properties"]["mcp_tool_refs"]["items"]

    def test_mcp_refs_stay_free_form_with_empty_or_malformed_resources(self):
        schema = build_edit_flow_tool_schema(
            [_make_step(1)],
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

        add_payload = schema["function"]["parameters"]["properties"]["operations"][
            "items"
        ]["properties"]["add_payload"]

        assert "enum" not in add_payload["properties"]["mcp_server_refs"]["items"]
        assert "enum" not in add_payload["properties"]["mcp_tool_refs"]["items"]

    def test_patch_schema_exposes_typed_previous_field_refs(self):
        schema = build_edit_flow_tool_schema([_make_step(1), _make_step(2)])
        patch = schema["function"]["parameters"]["properties"]["operations"]["items"][
            "properties"
        ]["patch"]

        previous_fields = patch["properties"]["uses_previous_fields"]
        assert previous_fields["items"]["required"] == ["from_step", "field_path"]
        assert "input_bindings" not in patch["properties"]
        assert "uses_form_fields" in patch["properties"]
        assert "typed `uses_previous_fields`" in patch["description"]

    def test_patch_schema_uses_generated_flow_schema_values(self):
        schema = build_edit_flow_tool_schema([_make_step(1), _make_step(2)])
        patch = schema["function"]["parameters"]["properties"]["operations"]["items"][
            "properties"
        ]["patch"]
        props = patch["properties"]

        assert props["input_source"]["enum"] == builder_input_source_values()
        assert props["input_type"]["enum"] == builder_input_type_values()
        assert "output_mode" not in props
        assert props["output_type"]["enum"] == builder_output_type_values()
        assert (
            props["document_delivery_mode"]["enum"] == document_delivery_mode_values()
        )
        assert props["review_mode"]["enum"] == ["view", "edit", None]


class TestBuildEditModeToolSchemas:
    def test_includes_edit_flow_and_discovery_tools(self):
        schemas = build_edit_mode_tool_schemas([_make_step(1)])
        names = [s["function"]["name"] for s in schemas]
        assert EDIT_FLOW_TOOL_NAME in names
        assert "ask_structured_question" in names
        assert "confirm_requirements" in names
